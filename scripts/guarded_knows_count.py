"""Guarded Knows check; offline by default, --execute requires approval.

Use --communities for baseline Louvain and exact within-community betweenness.
Compare --louvain-max-levels 1 5 --louvain-seeds 42 7 99 offline using saved RAI
rows plus a local NetworkX reference. Missing RAI runs require --execute and a
new --community-output file. No engine resume or deployment is attempted.
Add --routes to prepare/check 1-, 2-, 3-hop and unreachable person pairs.
Use --source-id ID --target-id ID for any pair, or --person-paths for the
non-seed, self, unreachable and reverse-direction regression suite.
Use --remaining-person-paths for only the reviewed 1-hop, 2-hop, self,
and unreachable examples, executed sequentially with stop-on-failure behavior.

Graph/oracle checks live in check_graphs.py. This entry point reuses the
source, engine, and mutation guards in guarded_people_count.py.
"""

if __name__ == "__main__":
    from guarded_people_count import main
    main(query_kind="knows")
