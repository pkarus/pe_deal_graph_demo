"""Stored procedure: strongest shortest introduction route between ANY two people.

Why this exists
    ``queries.q_person_path`` answers the same question live on the engine, but it adds a rule to the
    model for every new source person and pulls a whole single-source distance table to the client
    (40-70 s per call on 2.5K people). This procedure runs entirely in Snowflake over the ``KNOWS``
    table a deployment already materialized, so no reasoner is started and nothing is recomputed.

How it works (``PERSON_PATH(source_id, target_id, max_hops, min_strength)``)
    1. Bidirectional breadth-first search. Two frontiers grow one full layer at a time, always the
       smaller one, until they touch. The first touch gives the exact shortest distance.
    2. Only the people that lie on some shortest route are kept (walk back from the meeting layer).
    3. One pass over those layers keeps, per person, the strongest route so far (product of tie
       strengths, the warm-path ranking rule; exact ties go to the lowest route ids) and counts
       how many shortest routes exist.
    ``max_hops`` caps the search depth (default 12). ``min_strength`` ignores weaker ties (default
    0.0), which is the filtration-threshold experiment without redeploying anything.
    The procedure only runs SELECTs: each layer reads the ties of the current frontier with a
    literal ``SRC IN (...)`` list, which Snowflake prunes to a few micro-partitions of the sorted
    edge table. A search that would read more than MAX_EDGES_READ edges stops with a clear status.

Statuses: reachable | self | unreachable (a frontier ran dry) | beyond_max_hops | unknown_person |
search_too_large.

Usage
    python scripts/person_path_proc.py --fixture connected1m --install
    python scripts/person_path_proc.py --fixture connected1m --call P19079 SCALE_P000000042
    python scripts/person_path_proc.py --fixture connected1m --stress 40 --json artifacts/person_path_1m.json

``--install`` creates ``<BASE>_<FIXTURE>_PATHS`` holding a both-directions edge table sorted by
source (so each layer prunes to the frontier's micro-partitions) and the procedure. Existing
deployment schemas are only read.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pe_deal_graph import settings as _cfg  # noqa: E402

# fixture -> suffix of the deployment schema that holds KNOWS and PERSON
DEPLOYMENTS = {"baseline": "DEPLOY", "connected100k": "CONNECTED_100K", "connected1m": "CONNECTED_1M",
               "connected10m": "CONNECTED_10M"}
DEFAULT_MAX_HOPS = 12


def schemas(fixture: str) -> tuple[str, str]:
    """(deployment schema with KNOWS/PERSON, path schema this script owns)."""
    if fixture not in DEPLOYMENTS:
        raise ValueError(f"Unknown fixture {fixture!r}; expected one of {sorted(DEPLOYMENTS)}")
    return _cfg.schema(DEPLOYMENTS[fixture]), _cfg.schema(DEPLOYMENTS[fixture] + "_PATHS")


def edge_table_sql(deploy: str, paths: str) -> str:
    """Both directions of every Knows pair, sorted by source for partition pruning."""
    return f"""CREATE OR REPLACE TABLE {paths}.KNOWS_EDGES AS
SELECT SRC, DST, STRENGTH, EVIDENCE FROM (
    SELECT P1 AS SRC, P2 AS DST, STRENGTH, EVIDENCE FROM {deploy}.KNOWS
    UNION ALL
    SELECT P2 AS SRC, P1 AS DST, STRENGTH, EVIDENCE FROM {deploy}.KNOWS)
ORDER BY SRC"""


MAX_EDGES_READ = 3_000_000  # stop a search that would pull more edges than this into the procedure
IN_LIST_CHUNK = 4000        # ids per edge lookup; literal lists let Snowflake prune on the sorted SRC column

# The procedure body (JavaScript: it starts in milliseconds, a Python procedure costs ~4 s per call).
# __EDGES__, __PERSON__ and the three limits are filled in by procedure_sql().
HANDLER_JS = r"""
var maxHops = (MAX_HOPS === undefined || MAX_HOPS === null) ? __DEFAULT_MAX_HOPS__ : Math.floor(Number(MAX_HOPS));
var minStrength = Number(MIN_STRENGTH || 0);
var base = {source_id: SOURCE_ID, target_id: TARGET_ID, max_hops: maxHops, min_strength: minStrength};
function withBase(extra) { var out = {}; var k; for (k in base) out[k] = base[k]; for (k in extra) out[k] = extra[k]; return out; }
function quoted(ids) { return ids.map(function (i) { return "'" + String(i).replace(/'/g, "''") + "'"; }).join(","); }
function run(sql) {
    var rs = snowflake.execute({sqlText: sql}), n = rs.getColumnCount(), out = [];
    while (rs.next()) { var row = []; for (var c = 1; c <= n; c++) row.push(rs.getColumnValue(c)); out.push(row); }
    return out;
}
function nameOf(ids) {
    var names = {};
    run("SELECT ID, NAME FROM __PERSON__ WHERE ID IN (" + quoted(ids) + ")").forEach(function (r) { names[r[0]] = r[1]; });
    return names;
}
var names = nameOf([SOURCE_ID, TARGET_ID]);
if (!(SOURCE_ID in names) || !(TARGET_ID in names)) return withBase({status: "unknown_person"});
if (SOURCE_ID === TARGET_ID)
    return withBase({status: "self", distance: 0, route: [SOURCE_ID], route_names: [names[SOURCE_ID]]});

var adjacency = new Map(), edgesRead = 0;
function expand(frontier) {  // read the ties of every person in the frontier, one pruned SELECT per chunk
    var ids = Array.from(frontier).sort();
    ids.forEach(function (p) { adjacency.set(p, []); });
    for (var at = 0; at < ids.length; at += __IN_LIST_CHUNK__) {
        var rows = run("SELECT SRC, DST, STRENGTH FROM __EDGES__ WHERE SRC IN (" +
                       quoted(ids.slice(at, at + __IN_LIST_CHUNK__)) + ") AND STRENGTH >= " + minStrength);
        edgesRead += rows.length;
        rows.forEach(function (r) { adjacency.get(r[0]).push([r[1], Number(r[2])]); });
    }
}

// 1. Bidirectional BFS: grow the smaller frontier one full layer at a time until the two meet.
var depth = {S: new Map([[SOURCE_ID, 0]]), T: new Map([[TARGET_ID, 0]])};
var frontier = {S: new Set([SOURCE_ID]), T: new Set([TARGET_ID])};
var radius = {S: 0, T: 0}, distance = null;
while (distance === null && frontier.S.size > 0 && frontier.T.size > 0 && radius.S + radius.T < maxHops) {
    var side = frontier.S.size <= frontier.T.size ? "S" : "T", other = side === "S" ? "T" : "S";
    expand(frontier[side]);
    if (edgesRead > __MAX_EDGES_READ__)
        return withBase({status: "search_too_large", distance: null, route: [], route_names: [],
                         edges_read: edgesRead, detail: "Lower max_hops or raise min_strength."});
    radius[side] += 1;
    var reached = new Set();
    frontier[side].forEach(function (p) {
        adjacency.get(p).forEach(function (e) { if (!depth[side].has(e[0])) reached.add(e[0]); });
    });
    reached.forEach(function (p) {
        depth[side].set(p, radius[side]);
        if (depth[other].has(p)) {
            var d = radius[side] + depth[other].get(p);
            if (distance === null || d < distance) distance = d;
        }
    });
    frontier[side] = reached;
}
var explored = depth.S.size + depth.T.size;
if (distance === null) {
    var dry = frontier.S.size === 0 || frontier.T.size === 0;
    return withBase({status: dry ? "unreachable" : "beyond_max_hops", distance: null, route: [], route_names: [],
                     people_explored: explored, edges_read: edgesRead});
}

// 2. Position of each person on a shortest route: 0 = source ... distance = target. The source side
//    covers positions up to its radius; the target side covers the rest.
var layers = [];
for (var i = 0; i <= distance; i++) layers.push(new Set());
depth.S.forEach(function (d, p) { if (d <= distance) layers[d].add(p); });
depth.T.forEach(function (d, p) { if (d < radius.T) layers[distance - d].add(p); });

// 3. Strongest route layer by layer (product of tie strengths; exact ties -> lowest route ids).
//    Every edge between consecutive positions was read during the search, from one side or the other.
function routeBefore(a, b) {
    for (var k = 0; k < a.length; k++) { if (a[k] < b[k]) return true; if (a[k] > b[k]) return false; }
    return false;
}
var best = new Map([[SOURCE_ID, {strength: 1.0, route: [SOURCE_ID], routes: 1}]]);
for (var pos = 0; pos < distance; pos++) {
    var options = new Map();  // next person -> Map(previous person -> candidate)
    var offer = function (previous, next, tie) {
        var from = best.get(previous);
        if (!options.has(next)) options.set(next, new Map());
        if (!options.get(next).has(previous))
            options.get(next).set(previous, {strength: from.strength * tie, route: from.route.concat([next]),
                                             routes: from.routes});
    };
    layers[pos].forEach(function (p) {
        if (!best.has(p) || !adjacency.has(p)) return;
        adjacency.get(p).forEach(function (e) { if (layers[pos + 1].has(e[0])) offer(p, e[0], e[1]); });
    });
    layers[pos + 1].forEach(function (n) {  // the same edges seen from the target side
        if (!adjacency.has(n)) return;
        adjacency.get(n).forEach(function (e) { if (layers[pos].has(e[0]) && best.has(e[0])) offer(e[0], n, e[1]); });
    });
    options.forEach(function (byPrevious, next) {
        var top = -1, winner = null, routes = 0;
        byPrevious.forEach(function (o) { if (o.strength > top) top = o.strength; routes += o.routes; });
        byPrevious.forEach(function (o) {
            if (top - o.strength <= 1e-12 && (winner === null || routeBefore(o.route, winner.route))) winner = o;
        });
        best.set(next, {strength: winner.strength, route: winner.route, routes: routes});
    });
}
var found = best.get(TARGET_ID);
if (!found || found.route.length - 1 !== distance) throw "Shortest distance has no complete route witness";
var route = found.route;
names = nameOf(route);
var evidence = {};
run("SELECT SRC, DST, STRENGTH, EVIDENCE FROM __EDGES__ WHERE SRC IN (" + quoted(route.slice(0, -1)) +
    ") AND DST IN (" + quoted(route.slice(1)) + ")").forEach(function (r) {
    evidence[r[0] + ">" + r[1]] = {from: r[0], to: r[1], strength: Math.round(Number(r[2]) * 1e6) / 1e6, evidence: r[3]};
});
var hops = [];
for (var h = 0; h + 1 < route.length; h++) hops.push(evidence[route[h] + ">" + route[h + 1]]);
return withBase({status: "reachable", distance: distance, route: route,
                 route_names: route.map(function (p) { return names[p]; }),
                 route_strength: Math.round(found.strength * 1e6) / 1e6, shortest_route_count: found.routes,
                 hops: hops, people_explored: explored, edges_read: edgesRead});
"""


def procedure_sql(deploy: str, paths: str) -> str:
    body = HANDLER_JS
    for key, value in {"__EDGES__": f"{paths}.KNOWS_EDGES", "__PERSON__": f"{deploy}.PERSON",
                       "__DEFAULT_MAX_HOPS__": DEFAULT_MAX_HOPS, "__MAX_EDGES_READ__": MAX_EDGES_READ,
                       "__IN_LIST_CHUNK__": IN_LIST_CHUNK}.items():
        body = body.replace(key, str(value))
    assert "$$" not in body and "__" not in body
    return f"""CREATE OR REPLACE PROCEDURE {paths}.PERSON_PATH(
    SOURCE_ID VARCHAR, TARGET_ID VARCHAR, MAX_HOPS FLOAT DEFAULT {DEFAULT_MAX_HOPS}, MIN_STRENGTH FLOAT DEFAULT 0.0)
RETURNS VARIANT LANGUAGE JAVASCRIPT
COMMENT = 'Strongest shortest Knows route between any two people (bidirectional BFS over persisted edges; SELECT only).'
EXECUTE AS CALLER AS $$
{body}
$$"""


# --------------------------------------------------------------------------------------------
# Snowflake access (the same raiconfig connection the loaders use; SELECT plus this script's schema)
# --------------------------------------------------------------------------------------------
def connect():
    import snowflake.connector
    import yaml
    cfg = yaml.safe_load((ROOT / "raiconfig.yaml").read_text())
    c = cfg["connections"][cfg["default_connection"]]
    token = c.get("token") or Path(c["token_file_path"]).expanduser().read_text().strip()
    return snowflake.connector.connect(
        account=c["account"], user=c["user"], authenticator="programmatic_access_token", token=token,
        role=_cfg.ADMIN_ROLE, warehouse=_cfg.WAREHOUSE, database=_cfg.DATABASE)


def install(con, fixture: str) -> dict:
    deploy, paths = schemas(fixture)
    cur = con.cursor()
    knows = cur.execute(f"SELECT COUNT(*) FROM {deploy}.KNOWS").fetchone()[0]
    if not knows:
        raise RuntimeError(f"{deploy}.KNOWS is empty; deploy that fixture first")
    cur.execute(f"CREATE SCHEMA IF NOT EXISTS {paths}")
    started = time.perf_counter()
    cur.execute(edge_table_sql(deploy, paths))
    edge_seconds = time.perf_counter() - started
    edges = cur.execute(f"SELECT COUNT(*) FROM {paths}.KNOWS_EDGES").fetchone()[0]
    if edges != 2 * knows:
        raise RuntimeError(f"Edge table has {edges} rows, expected {2 * knows}")
    # An earlier build of this script declared MAX_HOPS as NUMBER; that overload would be ambiguous.
    cur.execute(f"DROP PROCEDURE IF EXISTS {paths}.PERSON_PATH(VARCHAR, VARCHAR, NUMBER, FLOAT)")
    cur.execute(procedure_sql(deploy, paths))
    cur.execute(f"GRANT USAGE ON SCHEMA {paths} TO ROLE {_cfg.DEPLOY_ROLE}")
    cur.execute(f"GRANT SELECT ON TABLE {paths}.KNOWS_EDGES TO ROLE {_cfg.DEPLOY_ROLE}")
    return {"fixture": fixture, "deployment": deploy, "path_schema": paths, "knows_pairs": knows,
            "edge_rows": edges, "edge_table_seconds": round(edge_seconds, 3)}


def call(con, fixture: str, source: str, target: str, max_hops: int = DEFAULT_MAX_HOPS,
         min_strength: float = 0.0) -> tuple[dict, float]:
    _, paths = schemas(fixture)
    cur = con.cursor()
    started = time.perf_counter()
    row = cur.execute(f"CALL {paths}.PERSON_PATH(%s, %s, %s, %s)",
                      (source, target, max_hops, min_strength)).fetchone()
    return json.loads(row[0]), time.perf_counter() - started


# --------------------------------------------------------------------------------------------
# Independent check: the same answer computed locally from the edge list (never from the procedure)
# --------------------------------------------------------------------------------------------
class LocalGraph:
    """Adjacency read once from the deployment's KNOWS table; plain BFS plus a strongest-route pass."""

    def __init__(self, con, deploy: str):
        import numpy as np
        cur = con.cursor()
        cur.execute(f"SELECT P1, P2, STRENGTH FROM {deploy}.KNOWS")
        frame = cur.fetch_pandas_all()
        ids = sorted(set(frame["P1"]) | set(frame["P2"]))
        self.index = {p: n for n, p in enumerate(ids)}
        self.ids = ids
        a = frame["P1"].map(self.index).to_numpy(dtype=np.int64)
        b = frame["P2"].map(self.index).to_numpy(dtype=np.int64)
        w = frame["STRENGTH"].to_numpy(dtype=float)
        src, dst, wt = np.concatenate([a, b]), np.concatenate([b, a]), np.concatenate([w, w])
        order = np.argsort(src, kind="stable")
        self.dst, self.wt = dst[order], wt[order]
        self.start = np.searchsorted(src[order], np.arange(len(ids) + 1))
        self.people = [r[0] for r in cur.execute(f"SELECT ID FROM {deploy}.PERSON").fetchall()]

    def expected(self, source: str, target: str, min_strength: float = 0.0):
        """(distance or None, best strength, number of shortest routes)."""
        if source == target:
            return 0, 1.0, 1
        if source not in self.index or target not in self.index:
            return None, None, 0
        s, t = self.index[source], self.index[target]
        best, count, frontier, depth = {s: 1.0}, {s: 1}, [s], 0
        seen = {s}
        while frontier and t not in best:
            nxt_best, nxt_count = {}, {}
            for u in frontier:
                for k in range(self.start[u], self.start[u + 1]):
                    v, w = int(self.dst[k]), float(self.wt[k])
                    if v in seen or w < min_strength:
                        continue
                    nxt_best[v] = max(nxt_best.get(v, 0.0), best[u] * w)
                    nxt_count[v] = nxt_count.get(v, 0) + count[u]
            seen.update(nxt_best)
            best, count, frontier, depth = nxt_best, nxt_count, list(nxt_best), depth + 1
        if t not in best:
            return None, None, 0
        return depth, best[t], count[t]

    def largest_component(self) -> list[str]:
        """Ids of the largest connected group (so sampled pairs are mostly reachable)."""
        from scipy.sparse import csr_matrix
        from scipy.sparse.csgraph import connected_components
        import numpy as np
        n = len(self.ids)
        matrix = csr_matrix((np.ones(len(self.dst), dtype=np.int8), self.dst, self.start), shape=(n, n))
        _, labels = connected_components(matrix, directed=False)
        biggest = np.bincount(labels).argmax()
        return [self.ids[i] for i in np.flatnonzero(labels == biggest)]

    def edge_strength(self, a: str, b: str):
        u, v = self.index.get(a), self.index.get(b)
        if u is None or v is None:
            return None
        for k in range(self.start[u], self.start[u + 1]):
            if int(self.dst[k]) == v:
                return float(self.wt[k])
        return None


def check(result: dict, graph: LocalGraph, source: str, target: str, max_hops: int, min_strength: float):
    """Raise unless the procedure's answer equals the local one; returns the expected distance."""
    distance, strength, routes = graph.expected(source, target, min_strength)
    if source == target:
        want = "self"
    elif distance is None:
        want = "unreachable"
    elif distance > max_hops:
        want = "beyond_max_hops"
    else:
        want = "reachable"
    if result["status"] != want:
        # A capped search cannot tell "unreachable" from "too far" unless a frontier ran dry.
        if not (want == "unreachable" and result["status"] == "beyond_max_hops"):
            raise AssertionError(f"{source}->{target}: status {result['status']}, expected {want}")
    if want != "reachable":
        return distance
    route = result["route"]
    if result["distance"] != distance or len(route) - 1 != distance or route[0] != source or route[-1] != target:
        raise AssertionError(f"{source}->{target}: distance/route mismatch {result} vs {distance}")
    if len(set(route)) != len(route):
        raise AssertionError(f"{source}->{target}: route repeats a person")
    product = 1.0
    for a, b in zip(route, route[1:]):
        w = graph.edge_strength(a, b)
        if w is None or w < min_strength:
            raise AssertionError(f"{source}->{target}: hop {a}-{b} is not a Knows edge")
        product *= w
    if abs(product - strength) > 1e-6 or abs(result["route_strength"] - strength) > 1e-6:
        raise AssertionError(f"{source}->{target}: strength {result['route_strength']} is not the best {strength}")
    if result["shortest_route_count"] != routes:
        raise AssertionError(f"{source}->{target}: {result['shortest_route_count']} routes, expected {routes}")
    return distance


def stress(con, fixture: str, pairs: int, seed: int = 7, max_hops: int = DEFAULT_MAX_HOPS,
           min_strength: float = 0.0) -> dict:
    """Random pairs plus self, reverse, isolated and unknown cases; every answer checked locally."""
    import random
    deploy, paths = schemas(fixture)
    started = time.perf_counter()
    graph = LocalGraph(con, deploy)
    load_seconds = time.perf_counter() - started
    rng = random.Random(seed)
    connected = graph.ids
    isolated = sorted(set(graph.people) - set(graph.index))
    component = graph.largest_component()
    cases = [(rng.choice(component), rng.choice(component)) for _ in range(pairs - pairs // 3)]
    cases += [(rng.choice(connected), rng.choice(connected)) for _ in range(pairs // 3)]
    cases += [(b, a) for a, b in cases[:3]]                      # reverse direction
    cases += [(cases[0][0], cases[0][0])]                        # self
    if isolated:
        cases += [(cases[0][0], isolated[0])]                    # nobody knows this person
    rows, by_hops = [], {}
    for source, target in cases:
        result, seconds = call(con, fixture, source, target, max_hops, min_strength)
        distance = check(result, graph, source, target, max_hops, min_strength)
        rows.append({"source": source, "target": target, "status": result["status"], "distance": distance,
                     "routes": result.get("shortest_route_count"), "explored": result.get("people_explored"),
                     "seconds": round(seconds, 3)})
        by_hops.setdefault(result["status"] if distance is None or result["status"] != "reachable"
                           else f"{distance} hops", []).append(seconds)
        print(f"PASS {source} -> {target}: {result['status']} {distance} "
              f"routes={result.get('shortest_route_count')} {seconds:.2f}s", flush=True)
    unknown, _ = call(con, fixture, cases[0][0], "NO_SUCH_PERSON")
    if unknown["status"] != "unknown_person":
        raise AssertionError(f"Unknown id returned {unknown}")
    timings = sorted(r["seconds"] for r in rows)
    return {"fixture": fixture, "path_schema": paths, "people": len(graph.people),
            "knows_pairs": len(graph.dst) // 2, "cases": len(rows), "passed": len(rows),
            "max_hops": max_hops, "min_strength": min_strength, "warehouse": _cfg.WAREHOUSE,
            "local_graph_load_seconds": round(load_seconds, 1),
            "seconds_median": round(statistics.median(timings), 3),
            "seconds_p95": round(timings[int(0.95 * (len(timings) - 1))], 3), "seconds_max": timings[-1],
            "seconds_by_case": {k: {"n": len(v), "median": round(statistics.median(v), 3), "max": round(max(v), 3)}
                                for k, v in sorted(by_hops.items())},
            "rows": rows}


def stress_persisted(con, fixture: str, pairs: int, seed: int = 7, max_hops: int = DEFAULT_MAX_HOPS) -> dict:
    """For graphs too large to copy locally (10M): check against the deployment's own stored distances.

    PERSONDISTANCEPROBE holds every distance from the five team seeds and was itself validated row by
    row against the independent oracle. Each sampled (seed, person, hops) row must come back with the
    same distance; every hop of every returned route must be a row of KNOWS; and a set of non-seed
    pairs must give the same distance, strength and route count in both directions. Strength
    optimality is NOT independently verified here (it is at 100K and 1M via ``--stress``).
    """
    deploy, paths = schemas(fixture)
    cur = con.cursor()
    people = cur.execute(f"SELECT COUNT(*) FROM {deploy}.PERSON").fetchone()[0]
    sample = cur.execute(f"SELECT SOURCE_ID, TARGET_ID, HOPS FROM {deploy}.PERSONDISTANCEPROBE "
                         f"ORDER BY HASH(SOURCE_ID, TARGET_ID, {seed}) LIMIT {pairs}").fetchall()
    others = [r[0] for r in cur.execute(f"SELECT ID FROM {deploy}.PERSON ORDER BY HASH(ID, {seed}) LIMIT {pairs // 2}").fetchall()]
    rows, by_hops, hop_pairs = [], {}, set()

    def record(source, target, result, seconds, kind):
        rows.append({"source": source, "target": target, "kind": kind, "status": result["status"],
                     "distance": result.get("distance"), "routes": result.get("shortest_route_count"),
                     "explored": result.get("people_explored"), "seconds": round(seconds, 3)})
        key = f"{result['distance']} hops" if result["status"] == "reachable" else result["status"]
        by_hops.setdefault(key, []).append(seconds)
        if result["status"] == "reachable":
            route = result["route"]
            if (len(route) - 1 != result["distance"] or len(result["hops"]) != result["distance"]
                    or route[0] != source or route[-1] != target or len(set(route)) != len(route)):
                raise AssertionError(f"{source}->{target}: malformed route {result}")
            hop_pairs.update(tuple(sorted(pair)) for pair in zip(route, route[1:]))
        print(f"PASS {kind} {source} -> {target}: {result['status']} {result.get('distance')} {seconds:.2f}s", flush=True)

    for source, target, hops in sample:
        result, seconds = call(con, fixture, source, target, max_hops)
        want = "self" if source == target else "reachable" if hops <= max_hops else "beyond_max_hops"
        if result["status"] != want or (want == "reachable" and result["distance"] != hops):
            raise AssertionError(f"{source}->{target}: {result} but the stored distance is {hops}")
        record(source, target, result, seconds, "seed")
    for a, b in zip(others[0::2], others[1::2]):
        forward, seconds = call(con, fixture, a, b, max_hops)
        record(a, b, forward, seconds, "any")
        backward, seconds = call(con, fixture, b, a, max_hops)
        record(b, a, backward, seconds, "reverse")
        same = ("status", "distance", "route_strength", "shortest_route_count")
        if any(forward.get(k) != backward.get(k) for k in same):
            raise AssertionError(f"{a}<->{b}: the two directions disagree: {forward} vs {backward}")
    # Every hop of every returned route must be a real Knows pair (one scan of the source-of-truth table).
    values = ",".join("('" + a.replace("'", "''") + "','" + b.replace("'", "''") + "')" for a, b in sorted(hop_pairs))
    found = cur.execute(f"SELECT COUNT(*) FROM {deploy}.KNOWS WHERE (P1, P2) IN ({values})").fetchone()[0] if values else 0
    if found != len(hop_pairs):
        raise AssertionError(f"{len(hop_pairs) - found} returned hops are not Knows pairs")
    timings = sorted(r["seconds"] for r in rows)
    return {"fixture": fixture, "path_schema": paths, "people": people, "cases": len(rows), "passed": len(rows),
            "checked_against": "stored seed distances (validated earlier against the independent oracle), "
                               "KNOWS membership of every hop, and forward/reverse agreement",
            "hops_verified_in_knows": len(hop_pairs), "max_hops": max_hops, "warehouse": _cfg.WAREHOUSE,
            "seconds_median": round(statistics.median(timings), 3),
            "seconds_p95": round(timings[int(0.95 * (len(timings) - 1))], 3), "seconds_max": timings[-1],
            "seconds_by_case": {k: {"n": len(v), "median": round(statistics.median(v), 3), "max": round(max(v), 3)}
                                for k, v in sorted(by_hops.items())},
            "rows": rows}



def team_introduction_1m(con, target: str, max_hops: int = DEFAULT_MAX_HOPS) -> dict:
    """Find routes from the current team using the existing 1M path procedure.

    Searches stored K1 connections on demand. It does not refresh RAI, rebuild
    communities, or calculate distances for other targets.
    """
    from pe_deal_graph import AS_OF_ISO
    deploy, _ = schemas('connected1m')
    source_schema = deploy + '_SRC'
    cur = con.cursor()
    person = cur.execute(f'SELECT ID, NAME FROM {deploy}.PERSON WHERE ID=%s', (target,)).fetchone()
    if person is None:
        return {'status': 'unknown_person', 'target_id': target, 'routes': []}
    seeds = cur.execute(f'''SELECT DISTINCT R.PERSON_ID, P.NAME
        FROM {source_schema}.ROLE_HISTORY R
        JOIN {source_schema}.SPONSOR S ON S.SPONSOR_ID=R.ORG_ID
        JOIN {deploy}.PERSON P ON P.ID=R.PERSON_ID
        WHERE S.NAME=%s AND R.ROLE_TYPE IN ('Deal Team','Operating Partner')
          AND R.START_DATE <= %s::DATE AND (R.END_DATE IS NULL OR R.END_DATE > %s::DATE)
        ORDER BY R.PERSON_ID''', ('Northwind Equity Partners', AS_OF_ISO, AS_OF_ISO)).fetchall()
    if not seeds:
        raise RuntimeError('No current team seeds found in the 1M sample')
    started = time.perf_counter()
    routes = []
    for source, name in seeds:
        route, elapsed = call(con, 'connected1m', source, target, max_hops)
        route.update(source_name=name, call_seconds=elapsed)
        routes.append(route)
    routes.sort(key=lambda r: (r.get('distance') if r.get('distance') is not None else float('inf'),
                               -(r.get('route_strength') or (1 if r['status'] == 'self' else 0)),
                               r['source_id']))
    ids = sorted({p for r in routes for p in r.get('route', [])})
    role_rows = []
    if ids:
        placeholders = ','.join(['%s'] * len(ids))
        role_rows = cur.execute(f'''SELECT R.PERSON_ID, R.ROLE_TYPE, R.TITLE, R.ORG_ID,
            COALESCE(C.NAME, S.NAME, I.NAME, R.ORG_ID), R.START_DATE, R.END_DATE
            FROM {source_schema}.ROLE_HISTORY R
            LEFT JOIN {source_schema}.COMPANY C ON C.COMPANY_ID=R.ORG_ID
            LEFT JOIN {source_schema}.SPONSOR S ON S.SPONSOR_ID=R.ORG_ID
            LEFT JOIN {source_schema}.INTERMEDIARY I ON I.INTERMEDIARY_ID=R.ORG_ID
            WHERE R.PERSON_ID IN ({placeholders}) AND R.START_DATE <= %s::DATE
              AND (R.END_DATE IS NULL OR R.END_DATE > %s::DATE)
            ORDER BY R.PERSON_ID, R.ORG_ID, R.ROLE_ID''', (*ids, AS_OF_ISO, AS_OF_ISO)).fetchall()
    roles = [{'person_id': r[0], 'role_type': r[1], 'title': r[2], 'organization_id': r[3],
              'organization_name': r[4], 'start_date': str(r[5]),
              'end_date': str(r[6]) if r[6] is not None else None} for r in role_rows]
    return {'target_id': person[0], 'target_name': person[1], 'as_of': AS_OF_ISO,
            'team_members': len(seeds), 'routes': routes, 'current_roles': roles,
            'ranking': 'fewest hops, then greatest product of modeled tie strengths',
            'seconds': time.perf_counter() - started,
            'method': 'Snowflake JavaScript/SQL path search on existing RAI-materialized connections'}


class SavedCommunity1M:
    """Use saved RAI memberships; optionally score only one community locally.

    Existing scores remain labeled exact or sampled. On-request exact scores are
    cached only in this instance, for the unchanged saved graph/partition snapshot.
    Create a new instance after any source refresh. This creates no database objects.
    """

    def __init__(self, con):
        self.con = con
        self.deploy, paths = schemas('connected1m')
        self.table = paths + '.PERSON_COMMUNITY_L5_S7_P50000_X200'
        self._exact = {}

    def query(self, person: str, *, exact: bool = False, top: int = 3) -> dict:
        if type(top) is not int or top < 1:
            raise ValueError('top must be a positive integer')
        started = time.perf_counter()
        cur = self.con.cursor()
        member = cur.execute(f'SELECT COMMUNITY FROM {self.table} WHERE ID=%s', (person,)).fetchone()
        if member is None:
            raise ValueError(f'No saved community for {person}')
        community = member[0]
        hit = exact and community in self._exact
        read_seconds = calculation_seconds = 0.0
        if hit:
            rows = self._exact[community]
        else:
            members = cur.execute(f'''SELECT C.ID, P.NAME, C.INTERNAL_BETWEENNESS, C.SAMPLED
                FROM {self.table} C JOIN {self.deploy}.PERSON P ON P.ID=C.ID
                WHERE C.COMMUNITY=%s ORDER BY C.ID''', (community,)).fetchall()
            rows = [{'id': r[0], 'name': r[1], 'score': float(r[2]), 'sampled': bool(r[3])}
                    for r in members]
            if exact:
                import networkx as nx
                edges = cur.execute(f'''SELECT K.P1, K.P2 FROM {self.deploy}.KNOWS K
                    JOIN {self.table} A ON A.ID=K.P1
                    JOIN {self.table} B ON B.ID=K.P2
                    WHERE A.COMMUNITY=%s AND B.COMMUNITY=%s''', (community, community)).fetchall()
                graph = nx.Graph()
                graph.add_nodes_from(r['id'] for r in rows)
                graph.add_edges_from(edges)
                read_seconds = time.perf_counter() - started
                calculation = time.perf_counter()
                scores = nx.betweenness_centrality(graph, normalized=False, weight=None)
                calculation_seconds = time.perf_counter() - calculation
                rows = [dict(r, score=scores[r['id']], sampled=False) for r in rows]
                self._exact[community] = rows
        ordered = sorted(rows, key=lambda r: (-r['score'], r['id']))
        cutoff = ordered[min(top, len(ordered)) - 1]['score']
        return {'person_id': person, 'community_id': community, 'members': len(rows),
                'membership_table': self.table,
                'method': 'local_exact_on_saved_community' if exact else 'saved_RAI_scores',
                'cache_hit': hit, 'sampled_people': sum(r['sampled'] for r in rows),
                'leaders': [r for r in ordered if r['score'] >= cutoff],
                'person': next(r for r in rows if r['id'] == person),
                'source_read_seconds': read_seconds, 'calculation_seconds': calculation_seconds,
                'request_seconds': time.perf_counter() - started,
                'communities_calculated_locally': len(self._exact)}



def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fixture", default="baseline", choices=sorted(DEPLOYMENTS))
    ap.add_argument("--print-sql", action="store_true", help="print the edge-table and procedure SQL; no connection")
    ap.add_argument("--install", action="store_true")
    ap.add_argument("--call", nargs=2, metavar=("SOURCE_ID", "TARGET_ID"))
    ap.add_argument("--stress", type=int, metavar="PAIRS", help="check against a local copy of the graph (up to ~1M people)")
    ap.add_argument("--stress-persisted", type=int, metavar="PAIRS",
                    help="check against the deployment's stored seed distances (for 10M)")
    ap.add_argument("--max-hops", type=int, default=DEFAULT_MAX_HOPS)
    ap.add_argument("--min-strength", type=float, default=0.0)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--json", type=Path, help="write the stress result here")
    ap.add_argument('--team-to', metavar='PERSON_ID', help='1M sample: routes from current team plus saved community')
    ap.add_argument('--exact-community', action='store_true', help='score the requested community locally instead of reading saved scores')
    args = ap.parse_args()
    if args.team_to and (args.fixture != 'connected1m' or args.install or args.stress or args.stress_persisted or args.call or args.print_sql):
        ap.error('--team-to is a standalone read/query action for --fixture connected1m')
    if args.team_to and args.min_strength != 0.0:
        ap.error('--team-to uses the saved threshold-0 community snapshot; min-strength must remain 0')
    if args.exact_community and not args.team_to:
        ap.error('--exact-community requires --team-to')
    deploy, paths = schemas(args.fixture)
    if args.print_sql:
        print(edge_table_sql(deploy, paths) + ";\n\n" + procedure_sql(deploy, paths) + ";")
        return 0
    con = connect()
    try:
        if args.team_to:
            report = team_introduction_1m(con, args.team_to, args.max_hops)
            if report.get('status') != 'unknown_person':
                report['community'] = SavedCommunity1M(con).query(args.team_to, exact=args.exact_community)
            print(json.dumps(report, indent=2))
            if args.json:
                args.json.write_text(json.dumps(report, indent=2) + '\n')
            return 0
        if args.install:
            print(json.dumps(install(con, args.fixture), indent=2))
        if args.call:
            result, seconds = call(con, args.fixture, *args.call, args.max_hops, args.min_strength)
            print(json.dumps(result, indent=2))
            print(f"{seconds:.2f} s", file=sys.stderr)
        if args.stress or args.stress_persisted:
            report = (stress(con, args.fixture, args.stress, args.seed, args.max_hops, args.min_strength)
                      if args.stress else stress_persisted(con, args.fixture, args.stress_persisted, args.seed, args.max_hops))
            print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=2))
            if args.json:
                args.json.write_text(json.dumps(report, indent=2) + "\n")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
