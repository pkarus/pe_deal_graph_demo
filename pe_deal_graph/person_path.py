"""Find one strongest shortest route directly from local employment records.

This local 10K experiment implements the demo's K1 employment/board-overlap rule.
It builds person/organization indexes, then derives connections only when a search
visits a person. It reads no saved Knows edges, distances, or community results.
Datasets containing deal or CRM records are rejected: K2/K3 are not implemented here.
This is Python execution, not a RelationalAI reasoner benchmark.

    python -m pe_deal_graph.person_path --csv-dir data/scale_connected_10k \
        --source P19079 --target SCALE_P000000004
"""
from __future__ import annotations

import argparse
import calendar
import csv
import json
import math
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from pe_deal_graph import AS_OF_ISO


def _rows(directory: Path, table: str):
    with (directory / f"{table}.csv").open(newline="") as stream:
        yield from csv.DictReader(stream)


@dataclass(frozen=True)
class Role:
    id: str
    person: str
    organization: str
    kind: str
    start: date
    end: date | None


class PersonPaths:
    """Read source records once; calculate each requested route from scratch."""

    def __init__(self, directory: Path, *, as_of: date = date.fromisoformat(AS_OF_ISO)):
        directory = Path(directory)
        # Refuse incomplete answers on the richer demo dataset.
        for table in ("TRANSACTION", "TRANSACTION_PARTY", "CRM_INTERACTION"):
            if (directory / f"{table}.csv").exists() and next(_rows(directory, table), None):
                raise ValueError(f"{table} contains data; this local experiment supports K1 roles only")
        self.as_of = as_of
        self.people = {}
        for row in _rows(directory, "PERSON"):
            pid = row["person_id"]
            if not pid or pid in self.people:
                raise ValueError(f"Missing or duplicate person ID: {pid!r}")
            self.people[pid] = row["full_name"]
        self.organizations = {}
        for table, key in (("COMPANY", "company_id"), ("SPONSOR", "sponsor_id"),
                           ("INTERMEDIARY", "intermediary_id")):
            if (directory / f"{table}.csv").exists():
                self.organizations.update((r[key], r["name"]) for r in _rows(directory, table))
        self.by_person = defaultdict(list)
        self.by_org = defaultdict(list)
        seen = set()
        for row in _rows(directory, "ROLE_HISTORY"):
            role = Role(row["role_id"], row["person_id"], row["org_id"], row["role_type"],
                        date.fromisoformat(row["start_date"]),
                        date.fromisoformat(row["end_date"]) if row["end_date"] else None)
            if role.id in seen or role.person not in self.people:
                raise ValueError(f"Duplicate role or unknown person in role {role.id}")
            if role.end is not None and role.end < role.start:
                raise ValueError(f"End before start in role {role.id}")
            seen.add(role.id)
            self.by_person[role.person].append(role)
            self.by_org[role.organization].append(role)
        self.role_count = len(seen)

    def _years_ago(self, years: int) -> date:
        year = self.as_of.year - years
        return self.as_of.replace(year=year, day=min(self.as_of.day,
                                     calendar.monthrange(year, self.as_of.month)[1]))

    def _connections(self, person: str, stats: dict) -> dict:
        """Derive this person's neighbors from shared organizations and dates."""
        neighbors = {}
        for a in self.by_person.get(person, ()):
            for b in self.by_org[a.organization]:
                if a.person == b.person:
                    continue
                stats["role_pairs_checked"] += 1
                start, end = max(a.start, b.start), min(a.end or self.as_of, b.end or self.as_of)
                days = (end - start).days
                if days < 365:
                    continue
                recency = 1.0 if end >= self._years_ago(10) else (0.7 if end >= self._years_ago(20) else 0.4)
                strength = recency * min(1.0, 0.4 + 0.15 * days / 365.25)
                evidence = {"kind": "K1", "role_ids": sorted((a.id, b.id)),
                            "organization_id": a.organization,
                            "organization": self.organizations.get(a.organization, a.organization),
                            "relationship": "board co-service" if a.kind == b.kind == "Board" else "tenure overlap",
                            "overlap_start": start.isoformat(), "overlap_end": end.isoformat(),
                            "overlap_days": days, "strength": strength}
                edge = neighbors.setdefault(b.person, {"strength": 0.0, "evidence": []})
                edge["strength"] = max(edge["strength"], strength)
                edge["evidence"].append(evidence)
        for edge in neighbors.values():
            edge["evidence"].sort(key=lambda e: (-e["strength"], e["role_ids"]))
        return neighbors

    def query(self, source: str, target: str, *, max_hops: int = 12, min_strength: float = 0.0) -> dict:
        """Breadth-first search; maximize strength product among shortest routes.

        One best prefix per person suffices; complete routes are never enumerated.
        Search state and derived edges are discarded after each call.
        """
        if type(max_hops) is not int or max_hops < 0:
            raise ValueError("max_hops must be a nonnegative integer")
        if not math.isfinite(min_strength) or not 0 <= min_strength <= 1:
            raise ValueError("min_strength must be between 0 and 1")
        started = time.perf_counter()
        stats = {"people_expanded": 0, "role_pairs_checked": 0, "people_reached": 0}
        result = {"source_id": source, "target_id": target, "as_of": self.as_of.isoformat(),
                  "method": "local_python_on_demand_K1", "max_hops": max_hops,
                  "min_strength": min_strength, "distance": None, "route": [], "route_names": [],
                  "route_strength": None, "hops": [], "shortest_route_count": 0}

        def finish(status):
            return dict(result, status=status, search=stats,
                        query_seconds=time.perf_counter() - started)

        if source not in self.people or target not in self.people:
            return finish("unknown_person")
        if source == target:
            result.update(distance=0, route=[source], route_names=[self.people[source]],
                          route_strength=1.0, shortest_route_count=1)
            stats["people_reached"] = 1
            return finish("self")

        distance, scores, paths, counts = {source: 0}, {source: 1.0}, {source: (source,)}, {source: 1}
        parents = {}
        frontier, depth = [source], 0
        while frontier:
            if depth >= max_hops:
                stats["people_reached"] = len(distance)
                return finish("beyond_max_hops")
            next_frontier = set()
            for person in frontier:
                stats["people_expanded"] += 1
                for other, edge in self._connections(person, stats).items():
                    if edge["strength"] < min_strength or distance.get(other, depth + 1) < depth + 1:
                        continue
                    candidate_score = scores[person] * edge["strength"]
                    candidate_path = paths[person] + (other,)
                    if other not in distance:
                        distance[other], scores[other], paths[other], counts[other] = depth + 1, -1.0, (), 0
                        next_frontier.add(other)
                    counts[other] += counts[person]
                    if (candidate_score > scores[other] or
                            (candidate_score == scores[other] and candidate_path < paths[other])):
                        scores[other], paths[other] = candidate_score, candidate_path
                        parents[other] = (person, edge)
            depth += 1
            if target in distance:
                route = list(paths[target])
                hops = [{"from": a, "to": b, **parents[b][1]} for a, b in zip(route, route[1:])]
                result.update(distance=depth, route=route, route_names=[self.people[p] for p in route],
                              route_strength=scores[target], shortest_route_count=counts[target], hops=hops)
                stats["people_reached"] = len(distance)
                return finish("reachable")
            frontier = sorted(next_frontier)
        stats["people_reached"] = len(distance)
        return finish("unreachable")


class CommunityConnectors:
    """Prepare local Louvain groups once; score a group only on its first request.

    The cache belongs to this in-memory graph snapshot. Construct a new instance
    after changing input data, the edge threshold, or Louvain settings. This uses
    NetworkX locally, not the RAI deployment. Path queries remain independent.
    """

    def __init__(self, records: PersonPaths, *, max_levels: int = 5, seed: int = 7,
                 min_strength: float = 0.0):
        import networkx as nx
        if type(max_levels) is not int or max_levels < 1:
            raise ValueError("max_levels must be a positive integer")
        if not math.isfinite(min_strength) or not 0 <= min_strength <= 1:
            raise ValueError("min_strength must be between 0 and 1")
        self.names = dict(records.people)
        self._scores = {}
        self._compute_seconds = {}
        started = time.perf_counter()
        graph = nx.Graph()
        graph.add_nodes_from(sorted(self.names))
        stats = {"role_pairs_checked": 0}
        for a in sorted(self.names):
            for b, edge in records._connections(a, stats).items():
                if a < b and edge["strength"] >= min_strength:
                    graph.add_edge(a, b, strength=edge["strength"])
        graph_seconds = time.perf_counter() - started
        started = time.perf_counter()
        groups = (nx.community.louvain_communities(graph, weight=None, seed=seed, max_level=max_levels)
                  if graph.number_of_edges() else [{p} for p in graph])
        self._groups = [frozenset(c) for c in sorted(groups, key=lambda c: min(c))]
        self._membership = {p: i for i, group in enumerate(self._groups) for p in group}
        self._graph = nx.freeze(graph)
        self.preparation = {"people": len(graph), "connections": graph.number_of_edges(),
                            "communities": len(groups), "max_levels": max_levels, "seed": seed,
                            "min_strength": min_strength, "as_of": records.as_of.isoformat(),
                            "graph_build_seconds": graph_seconds,
                            "community_detection_seconds": time.perf_counter() - started,
                            "betweenness_communities_computed": 0}

    def query(self, person: str, *, top: int = 3) -> dict:
        """Return exact internal connectors for this person's community, including cutoff ties."""
        import networkx as nx
        if type(top) is not int or top < 1:
            raise ValueError("top must be a positive integer")
        if person not in self._membership:
            raise ValueError(f"Unknown person: {person}")
        started = time.perf_counter()
        community = self._membership[person]
        reused = community in self._scores
        if not reused:
            calculation = time.perf_counter()
            self._scores[community] = nx.betweenness_centrality(
                self._graph.subgraph(self._groups[community]), normalized=False, weight=None)
            self._compute_seconds[community] = time.perf_counter() - calculation
        scores = self._scores[community]
        ordered = sorted(scores, key=lambda p: (-scores[p], p))
        cutoff = scores[ordered[min(top, len(ordered)) - 1]]
        return {"person_id": person, "person_name": self.names[person], "community_id": community,
                "community_size": len(scores), "person_betweenness": scores[person],
                "person_rank": 1 + sum(score > scores[person] for score in scores.values()),
                "leaders": [{"person_id": p, "name": self.names[p], "betweenness": scores[p]}
                            for p in ordered if scores[p] >= cutoff],
                "method": "local_networkx_exact_within_community", "cache_hit": reused,
                "calculation_seconds": self._compute_seconds[community],
                "communities_scored_so_far": len(self._scores),
                "request_seconds": time.perf_counter() - started}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--csv-dir", type=Path, default=Path("data/scale_connected_10k"))
    parser.add_argument("--source", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--max-hops", type=int, default=12)
    parser.add_argument("--min-strength", type=float, default=0.0)
    parser.add_argument("--community", action="store_true",
                        help="also prepare local communities and score only the target community")
    args = parser.parse_args()
    started = time.perf_counter()
    graph = PersonPaths(args.csv_dir)
    load_seconds = time.perf_counter() - started
    result = graph.query(args.source, args.target, max_hops=args.max_hops, min_strength=args.min_strength)
    result["input"] = {"people": len(graph.people), "roles": graph.role_count,
                       "load_and_index_seconds": load_seconds}
    if args.community:
        communities = CommunityConnectors(graph, min_strength=args.min_strength)
        result["community_preparation"] = communities.preparation
        result["target_community"] = communities.query(args.target)
    result["total_seconds"] = time.perf_counter() - started
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
