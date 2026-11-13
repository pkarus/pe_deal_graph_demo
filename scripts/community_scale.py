"""Communities and within-community connectors at scale, on the Logic reasoner, written back to a table.

What it does
    Reads the Knows graph a deployment already materialized (people + pairs; no role rules are
    re-run), finds Louvain communities, scores each person's betweenness inside their community
    (``pe_deal_graph/communities.py``: exact for small communities, sampled pivots for large
    ones) and writes ``(ID, COMMUNITY, INTERNAL_BETWEENNESS, SAMPLED)`` to a Snowflake table.

    The same query is then executed a second time on the same reasoner (``--repeat``), which
    separates the one-time cost of loading/indexing the source tables from the algorithm itself.

Usage
    python scripts/community_scale.py --fixture connected100k --prepare
    python scripts/community_scale.py --fixture connected100k --levels 5 --seed 7 --pivots 2000 --run --repeat 2 \
        --json artifacts/community_scale_100k_l5.json
    python scripts/community_scale.py --fixture connected100k --levels 5 --seed 7 --pivots 2000 --validate

``--prepare`` copies PERSON ids and KNOWS pairs into the fixture's ``_PATHS`` schema with change
tracking on (the reasoner streams from those copies, so the deployment's own tables are untouched).
``--pivots 0`` means exact everywhere (the original behaviour).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from pe_deal_graph import settings as _cfg  # noqa: E402
import person_path_proc as paths_tool  # noqa: E402  (schemas, connection, local graph)


def table_names(fixture: str, levels: int, seed: int, pivots: int, exact_up_to: int) -> dict:
    deploy, paths = paths_tool.schemas(fixture)
    mode = "EXACT" if not pivots else f"P{pivots}_X{exact_up_to}"
    return {"deploy": deploy, "schema": paths, "people": f"{paths}.GRAPH_PEOPLE", "pairs": f"{paths}.GRAPH_PAIRS",
            "output": f"{paths}.PERSON_COMMUNITY_L{levels}_S{seed}_{mode}"}


def prepare(con, fixture: str) -> dict:
    """Isolated, change-tracked copies of the materialized graph for the reasoner to stream."""
    t = table_names(fixture, 1, 42, 0, 0)
    cur = con.cursor()
    cur.execute(f"CREATE SCHEMA IF NOT EXISTS {t['schema']}")
    cur.execute(f"CREATE OR REPLACE TABLE {t['people']} CHANGE_TRACKING = TRUE AS SELECT ID FROM {t['deploy']}.PERSON")
    cur.execute(f"CREATE OR REPLACE TABLE {t['pairs']} CHANGE_TRACKING = TRUE AS SELECT P1, P2 FROM {t['deploy']}.KNOWS")
    people = cur.execute(f"SELECT COUNT(*), COUNT(DISTINCT ID) FROM {t['people']}").fetchone()
    pairs = cur.execute(f"SELECT COUNT(*), COUNT_IF(P1 >= P2) FROM {t['pairs']}").fetchone()
    if people[0] != people[1] or pairs[1]:
        raise RuntimeError("Graph copy is not one row per person / one row per ordered pair")
    return {"fixture": fixture, "people": people[0], "pairs": pairs[0], "people_table": t["people"],
            "pairs_table": t["pairs"]}


def build(fixture: str, levels: int, seed: int, pivots: int, exact_up_to: int, engine: str | None):
    """Define the model (no query runs here). Returns (model, select fragment builder, table names, people)."""
    os.environ.pop("DEBUG", None)
    os.environ["RAI_CONFIG_FILE_PATH"] = str(ROOT / "raiconfig.yaml")
    from relationalai.config import create_config
    from relationalai.semantics import Float, Integer, Model, String
    from relationalai.semantics.reasoners.graph import Graph
    from pe_deal_graph.communities import community_connectors

    t = table_names(fixture, levels, seed, pivots, exact_up_to)
    cfg = create_config()
    if engine:
        cfg.reasoners.logic.name = engine
    conn = cfg.get_default_connection()
    conn.role, conn.warehouse = _cfg.ADMIN_ROLE, _cfg.WAREHOUSE
    session = cfg.get_session()
    people = session.sql(f"SELECT COUNT(*) FROM {t['people']}").collect()[0][0]

    model = Model(f"pe_community_scale_{fixture}", config=cfg)
    people_table, pairs_table = model.Table(t["people"]), model.Table(t["pairs"])
    Person = model.Concept("Person", identify_by={"id": String})
    model.define(Person.new(id=people_table.ID))
    graph = Graph(model, directed=False, weighted=False, node_concept=Person)
    a, b = Person.ref(), Person.ref()
    model.where(a.id == pairs_table.P1, b.id == pairs_table.P2).define(graph.Edge.new(src=a, dst=b))
    labels, scores, sampled = community_connectors(
        model, Person, graph, max_levels=levels, randomization_seed=seed, exact_pivots=people,
        num_pivots=pivots or None, exact_up_to=exact_up_to)
    # One flag per person so the output says which scores are estimates.
    Person.estimate = model.Property(f"{Person} has estimate flag {Integer:estimate}")
    model.where(sampled(Person)).define(Person.estimate(1))
    model.where(model.not_(sampled(Person))).define(Person.estimate(0))

    def fragment():
        p, label, score = Person.ref(), Integer.ref(), Float.ref()
        return model.where(labels(p, label), scores(p, score)).select(
            p.id.alias("ID"), label.alias("COMMUNITY"), score.alias("INTERNAL_BETWEENNESS"),
            p.estimate.alias("SAMPLED"))

    return model, fragment, t, people, session, cfg.reasoners.logic.name


def run(args) -> dict:
    model, fragment, t, people, session, engine = build(args.fixture, args.levels, args.seed, args.pivots,
                                                        args.exact_up_to, args.engine)
    out = model.Table(t["output"])
    engine_row = session.sql("SELECT NAME, SIZE, STATUS FROM RELATIONALAI.API.REASONERS WHERE NAME = ?",
                             params=[engine]).collect()
    report = {"fixture": args.fixture, "people": people, "levels": args.levels, "seed": args.seed,
              "pivots": args.pivots or "exact", "exact_up_to": args.exact_up_to if args.pivots else None,
              "engine": engine, "engine_size": engine_row[0]["SIZE"] if engine_row else None,
              "output_table": t["output"], "runs": []}
    for attempt in range(1, args.repeat + 1):
        started = time.perf_counter()
        fragment().into(out).exec()
        seconds = time.perf_counter() - started
        rows = session.sql(f"SELECT COUNT(*), COUNT(DISTINCT COMMUNITY), SUM(SAMPLED) FROM {t['output']}").collect()[0]
        report["runs"].append({"attempt": attempt, "seconds": round(seconds, 1), "rows": rows[0],
                               "communities": rows[1], "people_with_sampled_score": int(rows[2] or 0)})
        print(json.dumps(report["runs"][-1]), flush=True)
        if args.json:
            args.json.write_text(json.dumps(report, indent=2) + "\n")
    return report


def validate(con, args) -> dict:
    """Independent check of the written table against a local copy of the graph (networkx)."""
    import random
    import networkx as nx
    import numpy as np
    from scipy.stats import spearmanr

    t = table_names(args.fixture, args.levels, args.seed, args.pivots, args.exact_up_to)
    graph = paths_tool.LocalGraph(con, t["deploy"])
    cur = con.cursor()
    cur.execute(f"SELECT ID, COMMUNITY, INTERNAL_BETWEENNESS, SAMPLED FROM {t['output']}")
    frame = cur.fetch_pandas_all()
    if len(frame) != len(graph.people) or frame["ID"].nunique() != len(frame):
        raise AssertionError(f"Output has {len(frame)} rows for {len(graph.people)} people")
    label_of = dict(zip(frame["ID"], frame["COMMUNITY"].astype(int)))
    score_of = dict(zip(frame["ID"], frame["INTERNAL_BETWEENNESS"].astype(float)))
    members: dict[int, list[str]] = {}
    for person, label in label_of.items():
        members.setdefault(label, []).append(person)
    sizes = sorted((len(v) for v in members.values()), reverse=True)

    # Modularity of the partition from the edge list (no graph library needed).
    index_label = np.array([label_of[p] for p in graph.ids])
    src = np.repeat(np.arange(len(graph.ids)), np.diff(graph.start))
    inside = index_label[src] == index_label[graph.dst]
    m2 = len(graph.dst)  # 2 * number of edges
    degree_sum: dict[int, int] = {}
    for label, degree in zip(index_label, np.diff(graph.start)):
        degree_sum[label] = degree_sum.get(label, 0) + int(degree)
    modularity = inside.sum() / m2 - sum((d / m2) ** 2 for d in degree_sum.values())

    def community_graph(people):
        keep = set(people)
        g = nx.Graph()
        g.add_nodes_from(people)
        for person in people:
            u = graph.index.get(person)
            if u is None:
                continue
            for k in range(graph.start[u], graph.start[u + 1]):
                other = graph.ids[int(graph.dst[k])]
                if other in keep and person < other:
                    g.add_edge(person, other)
        return g

    rng = random.Random(11)
    exact_groups = [m for m in members.values() if not args.pivots or len(m) <= args.exact_up_to]
    sampled_groups = sorted((m for m in members.values() if args.pivots and len(m) > args.exact_up_to),
                            key=len, reverse=True)
    checked_exact, worst = 0, 0.0
    for group in rng.sample(exact_groups, min(args.check_exact, len(exact_groups))):
        want = nx.betweenness_centrality(community_graph(group), normalized=False)
        for person, value in want.items():
            error = abs(score_of[person] - value)
            worst = max(worst, error)
            if error > 1e-5 + 2e-6 * abs(value):
                raise AssertionError(f"{person}: betweenness {score_of[person]} but exact is {value}")
        checked_exact += 1
    agreement = []
    # largest, smallest and a few in between: accuracy depends on how many pivots land in a community
    picks = sampled_groups[:1] + sampled_groups[-1:] + rng.sample(sampled_groups, min(max(args.check_sampled - 2, 0),
                                                                                    len(sampled_groups)))
    for group in picks[:args.check_sampled]:
        want = nx.betweenness_centrality(community_graph(group), normalized=False)
        ordered = sorted(group)
        rho = spearmanr([want[p] for p in ordered], [score_of[p] for p in ordered]).statistic
        top = max(10, len(group) // 100)
        best_exact = set(sorted(ordered, key=lambda p: -want[p])[:top])
        best_sampled = set(sorted(ordered, key=lambda p: -score_of[p])[:top])
        top1 = max(ordered, key=lambda p: want[p])
        agreement.append({"members": len(group), "spearman": round(float(rho), 4), "top_n": top,
                          "top_n_overlap": round(len(best_exact & best_sampled) / top, 3),
                          "exact_top1_in_sampled_top_n": top1 in best_sampled})
    return {"output_table": t["output"], "people": len(frame), "communities": len(members),
            "largest_community": sizes[0], "median_community": sizes[len(sizes) // 2],
            "singletons": sum(1 for s in sizes if s == 1), "modularity": round(float(modularity), 4),
            "people_with_sampled_score": int(frame["SAMPLED"].astype(int).sum()),
            "exact_communities_checked": checked_exact, "exact_max_abs_error": worst,
            "sampled_communities_checked": agreement}


def validate_in_warehouse(con, args) -> dict:
    """The same checks for graphs too large to copy locally (10M): totals and modularity are computed
    in Snowflake, and only the sampled communities' own edges are pulled down for the exact comparison."""
    import random
    import networkx as nx
    from scipy.stats import spearmanr

    t = table_names(args.fixture, args.levels, args.seed, args.pivots, args.exact_up_to)
    cur = con.cursor()
    people = cur.execute(f"SELECT COUNT(*) FROM {t['people']}").fetchone()[0]
    rows, distinct, sampled = cur.execute(
        f"SELECT COUNT(*), COUNT(DISTINCT ID), SUM(SAMPLED) FROM {t['output']}").fetchone()
    if rows != people or distinct != rows:
        raise AssertionError(f"Output has {rows} rows ({distinct} distinct) for {people} people")
    sizes = {int(c): (int(n), int(flag)) for c, n, flag in cur.execute(
        f"SELECT COMMUNITY, COUNT(*), MAX(SAMPLED) FROM {t['output']} GROUP BY 1").fetchall()}
    labelled = (f"SELECT a.COMMUNITY AS CA, b.COMMUNITY AS CB FROM {t['pairs']} k "
                f"JOIN {t['output']} a ON a.ID = k.P1 JOIN {t['output']} b ON b.ID = k.P2")
    inside, edges = cur.execute(f"SELECT COUNT_IF(CA = CB), COUNT(*) FROM ({labelled})").fetchone()
    degree = cur.execute(f"SELECT SUM(D * D) FROM (SELECT C, SUM(N) AS D FROM ("
                         f"SELECT CA AS C, COUNT(*) AS N FROM ({labelled}) GROUP BY 1 UNION ALL "
                         f"SELECT CB AS C, COUNT(*) AS N FROM ({labelled}) GROUP BY 1) GROUP BY 1)").fetchone()[0]
    modularity = inside / edges - float(degree) / (2 * edges) ** 2

    rng = random.Random(11)
    exact_labels = [c for c, (n, flag) in sizes.items() if not flag and n > 2]
    sampled_labels = sorted((c for c, (n, flag) in sizes.items() if flag), key=lambda c: -sizes[c][0])
    pick_exact = rng.sample(exact_labels, min(args.check_exact, len(exact_labels)))
    pick_sampled = (sampled_labels[:1] + sampled_labels[-1:] +
                    rng.sample(sampled_labels, min(max(args.check_sampled - 2, 0), len(sampled_labels))))[:args.check_sampled]
    chosen = ",".join(str(c) for c in pick_exact + pick_sampled)
    score_of, members = {}, {}
    for person, label, score in cur.execute(
            f"SELECT ID, COMMUNITY, INTERNAL_BETWEENNESS FROM {t['output']} WHERE COMMUNITY IN ({chosen})").fetchall():
        score_of[person] = float(score)
        members.setdefault(int(label), []).append(person)
    graphs = {label: nx.Graph() for label in members}
    for label, people_in in members.items():
        graphs[label].add_nodes_from(people_in)
    for p1, p2, label in cur.execute(
            f"SELECT k.P1, k.P2, a.COMMUNITY FROM {t['pairs']} k JOIN {t['output']} a ON a.ID = k.P1 "
            f"JOIN {t['output']} b ON b.ID = k.P2 WHERE a.COMMUNITY = b.COMMUNITY AND a.COMMUNITY IN ({chosen})").fetchall():
        graphs[int(label)].add_edge(p1, p2)
    worst = 0.0
    for label in pick_exact:
        for person, value in nx.betweenness_centrality(graphs[label], normalized=False).items():
            error = abs(score_of[person] - value)
            worst = max(worst, error)
            if error > 1e-5 + 2e-6 * abs(value):
                raise AssertionError(f"{person}: betweenness {score_of[person]} but exact is {value}")
    agreement = []
    for label in pick_sampled:
        want = nx.betweenness_centrality(graphs[label], normalized=False)
        ordered = sorted(members[label])
        rho = spearmanr([want[p] for p in ordered], [score_of[p] for p in ordered]).statistic
        top = max(10, len(ordered) // 100)
        best_exact = set(sorted(ordered, key=lambda p: -want[p])[:top])
        best_sampled = set(sorted(ordered, key=lambda p: -score_of[p])[:top])
        agreement.append({"members": len(ordered), "spearman": round(float(rho), 4), "top_n": top,
                          "top_n_overlap": round(len(best_exact & best_sampled) / top, 3),
                          "exact_top1_in_sampled_top_n": max(ordered, key=lambda p: want[p]) in best_sampled})
    ordered_sizes = sorted((n for n, _ in sizes.values()), reverse=True)
    return {"output_table": t["output"], "people": rows, "communities": len(sizes),
            "largest_community": ordered_sizes[0], "median_community": ordered_sizes[len(ordered_sizes) // 2],
            "singletons": sum(1 for n in ordered_sizes if n == 1), "modularity": round(float(modularity), 4),
            "people_with_sampled_score": int(sampled or 0), "exact_communities_checked": len(pick_exact),
            "exact_max_abs_error": worst, "sampled_communities_checked": agreement,
            "method": "totals and modularity in Snowflake; sampled communities recomputed locally"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fixture", default="connected100k", choices=sorted(paths_tool.DEPLOYMENTS))
    ap.add_argument("--levels", type=int, default=1)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--pivots", type=int, default=0, help="sampled pivots for large communities; 0 = exact everywhere")
    ap.add_argument("--exact-up-to", type=int, default=200, help="communities up to this size stay exact")
    ap.add_argument("--engine", help="Logic reasoner name (default: the one in raiconfig.yaml)")
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--repeat", type=int, default=1, help="execute the same query this many times")
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--check-exact", type=int, default=300, help="exactly-scored communities to recompute locally")
    ap.add_argument("--check-sampled", type=int, default=6, help="sampled communities to compare with exact locally")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    result = {}
    if args.prepare:
        con = paths_tool.connect()
        try:
            result["prepare"] = prepare(con, args.fixture)
        finally:
            con.close()
        print(json.dumps(result["prepare"], indent=2))
    if args.run:
        result.update(run(args))
    if args.validate:
        con = paths_tool.connect()
        try:
            big = con.cursor().execute(
                f"SELECT COUNT(*) FROM {table_names(args.fixture, 1, 42, 0, 0)['people']}").fetchone()[0] > 2_000_000
            result["validation"] = (validate_in_warehouse if big else validate)(con, args)
        finally:
            con.close()
        print(json.dumps(result["validation"], indent=2))
    if args.json and result:
        previous = json.loads(args.json.read_text()) if args.json.exists() and not args.run else {}
        previous.update(result)
        args.json.write_text(json.dumps(previous, indent=2, default=str) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
