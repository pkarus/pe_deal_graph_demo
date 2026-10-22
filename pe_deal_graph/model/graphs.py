"""Graph layer of the Northwind deal graph (owner: R10 Graph Engineer).

Three networks answer the graph half of the demo. Importing this module adds the graph definitions
and the rules that write every algorithm output into the contract names declared in core.py
(ONTOLOGY.md section 5). Nothing here runs a query at import time.

1. Warm-path graph (Q-PATH, Finale). People are nodes; two people are linked when they know each
   other (R09's ``Knows``, one edge per pair). We measure how many introductions separate each
   Northwind deal-team member or operating partner from everyone else, then rebuild the actual
   shortest introduction routes to each decision-maker and rank equal-length routes by tie strength.
2. Deal-flow graph (Q-FLOW). Intermediaries, sponsors and companies are nodes; they are linked when
   they sat on the same thesis-sector deal in the last 5 years. Betweenness says who bridges deal
   flow (exact, not sampled); PageRank is a secondary "reach" column for display.
3. Commercial graph (Q-CONFLICT, Q-ADDON backup). Companies are nodes; a supplier-customer link is
   an edge. We measure how many commercial links separate a bid subject from every company, so the
   rules can find our holdings within 2 links. The same graph gives add-on similarity for the backup.

Usage
    from pe_deal_graph.model import model
    import pe_deal_graph.model.rules    # R09: Knows, OurSeed, DecisionMaker, DealFlowTransaction, ...
    import pe_deal_graph.model.graphs   # this module
    graphs.validate_graphs()            # node and edge counts first (logged), then query the outputs

Verified constraints (relationalai 1.27.1, research/pyrel_cheatsheet.md):
- ``distance`` cannot take ``from_`` and ``to`` together, so path reconstruction uses two
  single-sided calls and the identity seed_hops(s, m) + dm_hops(dm, m) == hops(s, dm).
- ``betweenness_centrality`` samples 100 pivots by default; ``num_pivots=BETWEENNESS_PIVOTS``
  (16000 >= |V|) makes it exact Brandes, matching networkx ``normalized=False``.
- Graph ``from_`` sets are passed as unary Relationships (the verified form).
- Mixed asc/desc inside ``rank`` is rejected, so numeric keys are negated.
"""

from __future__ import annotations

import logging

from relationalai.semantics import Float, Integer, String
from relationalai.semantics.reasoners.graph import Graph
from relationalai.semantics.std import aggregates as aggs
from relationalai.semantics.std import math, strings
from relationalai.semantics.std.aggregates import asc, rank

from .core import (
    BETWEENNESS_PIVOTS,
    MAX_PATH_HOPS,
    BuyingFund,
    Company,
    ConflictSubject,
    DealFlowTransaction,
    DecisionMaker,
    Intermediary,
    Knows,
    NorthwindHolding,
    Organization,
    Ownership,
    OurSeed,
    Person,
    Transaction,
    TransactionParty,
    WarmPath,
    WarmPathHop,
    model,
)

log = logging.getLogger("pe_deal_graph.graphs")

# --------------------------------------------------------------------------------------------
# Constants (graph layer only)
# --------------------------------------------------------------------------------------------
MAX_RANKED_PATHS = 3  # best route plus up to 2 alternates per (target, decision-maker)
# Decision-maker distances are computed for targets that are Tier A today (score >= 70) or could
# reach Tier A with the finale's 10 warm-path points (score >= 60). This keeps the second distance
# call small while covering every target the demo can show a path for, before or after the finale.
TIER_A_MIN_SCORE = 70
WARM_PATH_POINTS = 10
PATH_SCOPE_MIN_SCORE = TIER_A_MIN_SCORE - WARM_PATH_POINTS
ADVISOR_ROLES = ("sell_side_advisor", "buy_side_advisor", "debt_advisor")  # lenders are not advisors
ADVISOR_COUNTERPARTY_ROLES = ("buyer", "seller", "owner")
PRINCIPAL_ROLES = ("buyer", "owner")  # in a recap the owner stands in for the buyer
LOUVAIN_SEED = 42  # CONFIG RANDOM_SEED; louvain is repeatable for a fixed seed and fixed input
BETWEENNESS_ROUND_DP = 3  # rank on rounded betweenness: engine values match networkx to ~5e-9 relative
                          # (single-precision level), so exact ties must not be split by float noise

# --------------------------------------------------------------------------------------------
# Graph-layer helpers (not contract names; used only inside this module)
# --------------------------------------------------------------------------------------------
# Unary "from_" sets for the distance and similarity calls.
_is_seed_node = model.Relationship(f"{Person:node} is a Northwind introduction seed")
_is_path_decision_maker = model.Relationship(f"{Person:node} decides on a target in warm-path scope")
_is_conflict_subject_node = model.Relationship(f"{Company:node} is a bid subject under conflict check")
_is_platform_node = model.Relationship(f"{Company:node} is a Fund IV platform")
# Symmetric view of the strongest Knows evidence, for hop-by-hop path text.
_tie_evidence = model.Relationship(f"{Person:person} is tied to {Person:other} by {String:evidence}")
# Every shortest route before ranking; WarmPath keeps the best MAX_RANKED_PATHS of these.
WarmPathCandidate = model.Concept(
    "WarmPathCandidate", identify_by={"target": Company, "decision_maker": Person, "route": String})
WarmPathCandidate.seed = model.Property(f"{WarmPathCandidate} starts at {Person:seed}")
WarmPathCandidate.hops = model.Property(f"{WarmPathCandidate} has {Integer:hops} hops")
WarmPathCandidate.strength = model.Property(f"{WarmPathCandidate} has {Float:strength}")
WarmPathCandidate.evidence = model.Property(f"{WarmPathCandidate} is evidenced by {String:evidence}")
WarmPathCandidate.node = model.Property(
    f"{WarmPathCandidate} visits at position {Integer:position} {Person:person}")
# Organizations that sit on at least one thesis deal edge: the deal-flow graph's node set.
DealFlowNode = model.Concept("DealFlowNode", extends=[Organization])


# ============================================================================================
# 1. Warm-path graph (Q-PATH, Finale)
# ============================================================================================
def build_warm_path_graph() -> Graph:
    """Who knows whom: one link per pair of people with any evidence of knowing each other.

    People are the nodes (everyone, including people nobody knows). A link means R09's Knows rule
    found overlapping tenure, board co-service, a shared deal or positive CRM contact. Links carry no
    direction and no weight here: the graph measures how many introductions apart two people are,
    and tie strength is applied afterwards when routes of the same length are compared.
    """
    g = Graph(model, directed=False, weighted=False, node_concept=Person)
    model.define(g.Edge.new(src=Knows.p1, dst=Knows.p2))
    return g


def define_seed_distances(g: Graph) -> None:
    """How many introductions each person is from each of our deal-team members and operating partners.

    Seeds are R09's OurSeed (current Northwind Deal Team or Operating Partner). One single-sided
    distance call from the seed set gives Person.seed_hops(seed, person, hops); the nearest seed's
    count is Person.nearest_seed_hops, which the Finale reuses for "reach the CEO in two hops or
    fewer". People nobody on our team can reach get no distance at all (they are cold).
    """
    model.where(OurSeed(Person)).define(_is_seed_node(Person))
    d_seed = g.distance(from_=_is_seed_node)
    s, p = Person.ref(), Person.ref()
    h = Integer.ref()
    model.where(d_seed(s, p, h)).define(Person.seed_hops(s, p, h))
    s2, h2 = Person.ref(), Integer.ref()
    model.define(Person.nearest_seed_hops(aggs.min(h2).per(Person).where(Person.seed_hops(s2, Person, h2))))


def define_decision_maker_distances(g: Graph) -> None:
    """How far each person is from the people who decide on a sale of our priority targets.

    Decision-makers are R09's DecisionMaker (the CEO, plus the owning sponsor's board designee),
    limited to targets scoring PATH_SCOPE_MIN_SCORE or more (Tier A today, or Tier A once the
    finale's warm-path points are added). This is the second single-sided distance call: together
    with the seed distances it tells us which people sit on a shortest route. It also writes
    DecisionMaker.hops (introductions from our nearest seed) and flags decision-makers with no
    route within MAX_PATH_HOPS as cold.
    """
    p, c = Person.ref(), Company.ref()
    model.where(DecisionMaker.person(p), DecisionMaker.target(c), c.score >= PATH_SCOPE_MIN_SCORE).define(
        _is_path_decision_maker(p))
    d_dm = g.distance(from_=_is_path_decision_maker)
    t, m = Person.ref(), Person.ref()
    h = Integer.ref()
    # Contract field order is (decision_maker, person, dm_hops): see core.py reading.
    model.where(d_dm(t, m, h)).define(Person.dm_hops(t, m, h))

    p2, h2 = Person.ref(), Integer.ref()
    model.where(DecisionMaker.person(p2), p2.nearest_seed_hops(h2)).define(DecisionMaker.hops(h2))
    model.where(DecisionMaker.hops > MAX_PATH_HOPS).define(DecisionMaker.is_cold())
    model.where(model.not_(DecisionMaker.hops)).define(DecisionMaker.is_cold())


def define_warm_paths(max_hops: int = MAX_PATH_HOPS) -> None:
    """Our warmest introduction routes to each decision-maker, hop by hop, with evidence.

    A route is a chain of people who know each other, from one of our seeds to the decision-maker,
    exactly as long as the decision-maker's distance from our nearest seed (so only shortest routes,
    at most MAX_PATH_HOPS introductions). Every middle person m must satisfy the distance identity
    seed_hops(seed, m) + dm_hops(decision-maker, m) == route length, which is how the routes are
    rebuilt from the two distance calls. A route's strength is the product of its tie strengths;
    routes of equal length are ranked strongest first (then by route, for a stable order), and the
    best plus up to two alternates become WarmPath rows with one WarmPathHop per introduction.
    """
    k = Knows.ref()
    a, b = Person.ref(), Person.ref()
    e = String.ref()
    model.where(k.p1(a), k.p2(b), k.evidence(e)).define(_tie_evidence(a, b, e), _tie_evidence(b, a, e))

    for length in range(1, max_hops + 1):
        dm, tgt = DecisionMaker.ref(), Company.ref()
        n = [Person.ref() for _ in range(length + 1)]  # n[0] = seed, n[length] = decision-maker
        w = [Float.ref() for _ in range(length)]
        ev = [String.ref() for _ in range(length)]
        conds = [dm.target(tgt), dm.person(n[length]), dm.hops == length,
                 _is_path_decision_maker(n[length]), Person.seed_hops(n[0], n[length], length)]
        for i in range(1, length):  # distance identity for every middle person
            ds, dd = Integer.ref(), Integer.ref()
            conds += [Person.seed_hops(n[0], n[i], ds), Person.dm_hops(n[length], n[i], dd),
                      ds == i, ds + dd == length]
        for i in range(length):  # consecutive people know each other
            conds += [Person.tie_strength(n[i], n[i + 1], w[i]), _tie_evidence(n[i], n[i + 1], ev[i])]
        strength = w[0]
        for x in w[1:]:
            strength = strength * x
        route_parts, text_parts = [n[0].id], [n[0].name]
        for i in range(1, length + 1):
            route_parts += [">", n[i].id]
            text_parts += [" -[", ev[i - 1], "]- ", n[i].name]
        c = WarmPathCandidate.ref()
        model.where(*conds).define(
            c := WarmPathCandidate.new(target=tgt, decision_maker=n[length], route=strings.concat(*route_parts)),
            c.seed(n[0]), c.hops(length), c.strength(strength), c.evidence(strings.concat(*text_parts)),
            *[c.node(i, n[i]) for i in range(length + 1)],
        )

    # Rank equal-length routes per (target, decision-maker): strongest first, then route id order.
    c, tgt, p = WarmPathCandidate.ref(), Company.ref(), Person.ref()
    model.where(
        c.target(tgt), c.decision_maker(p),
        r := rank(asc(0.0 - c.strength), asc(c.route)).per(tgt, p), r <= MAX_RANKED_PATHS,
    ).define(
        wp := WarmPath.new(target=tgt, decision_maker=p, route=c.route),
        wp.seed(c.seed), wp.hops(c.hops), wp.strength(c.strength), wp.evidence(c.evidence), wp.path_rank(r),
    )

    # One hop row per introduction, seed side first.
    for step in range(1, max_hops + 1):
        wp, c = WarmPath.ref(), WarmPathCandidate.ref()
        tgt, p = Company.ref(), Person.ref()
        rt = String.ref()
        x, y = Person.ref(), Person.ref()
        hw, he = Float.ref(), String.ref()
        model.where(
            wp.target(tgt), wp.decision_maker(p), wp.route(rt),
            c.target(tgt), c.decision_maker(p), c.route(rt),
            c.node(step - 1, x), c.node(step, y),
            Person.tie_strength(x, y, hw), _tie_evidence(x, y, he),
        ).define(
            hop := WarmPathHop.new(path=wp, step=step),
            hop.from_person(x), hop.to_person(y), hop.strength(hw), hop.evidence(he),
        )


# ============================================================================================
# 2. Deal-flow graph (Q-FLOW)
# ============================================================================================
def _deal_flow_pair(conds: list, x, y) -> None:
    """Record one undirected deal-flow link between x and y, stored once with the smaller id first."""
    model.where(*conds, x.id < y.id).define(x.deal_flow_partner(y))
    model.where(*conds, y.id < x.id).define(y.deal_flow_partner(x))


def define_deal_flow_links() -> None:
    """Who sat across the table from whom on thesis-sector deals in the last 5 years.

    Deals are R09's DealFlowTransaction (closed in the 5 years before AS_OF, target in the Fund IV
    thesis). On each deal we link every advisor (sell-side, buy-side or debt advisor; lenders are not
    advisors) to the target and to the buyer, seller and owner, and we link the buyer to the target.
    In a recap with no change of control the owner stands in for the buyer. A sponsor party is the
    sponsor itself (its fund is only the vehicle) and an add-on buyer is the platform company.
    Each pair is one link however many deals it shares: Organization.deal_flow_partner(a, b), a.id < b.id.
    """
    t = Transaction.ref()
    pa, pb = TransactionParty.ref(), TransactionParty.ref()
    x, y = Organization.ref(), Organization.ref()
    tgt = Company.ref()
    # advisor - target
    _deal_flow_pair([DealFlowTransaction(t), pa.transaction(t), pa.party_role.in_(list(ADVISOR_ROLES)),
                     pa.organization(x), t.target(tgt)], x, tgt)
    # advisor - buyer / seller / owner
    _deal_flow_pair([DealFlowTransaction(t), pa.transaction(t), pa.party_role.in_(list(ADVISOR_ROLES)),
                     pa.organization(x), pb.transaction(t),
                     pb.party_role.in_(list(ADVISOR_COUNTERPARTY_ROLES)), pb.organization(y)], x, y)
    # buyer (or owner in a recap) - target
    _deal_flow_pair([DealFlowTransaction(t), pb.transaction(t), pb.party_role.in_(list(PRINCIPAL_ROLES)),
                     pb.organization(y), t.target(tgt)], y, tgt)

    a, b = Organization.ref(), Organization.ref()
    model.where(a.deal_flow_partner(b)).define(DealFlowNode(a), DealFlowNode(b))


def build_deal_flow_graph() -> Graph:
    """The deal-flow network: firms linked by shared thesis-sector deals in the last 5 years.

    Nodes are only the organizations that appear on at least one such deal (intermediaries,
    sponsors, companies), so "intermediaries in the graph" means intermediaries active in our
    sectors. Undirected and unweighted, because betweenness needs an unweighted graph and the
    question is who connects whom, not how often.
    """
    define_deal_flow_links()
    g = Graph(model, directed=False, weighted=False, node_concept=DealFlowNode)
    a, b = DealFlowNode.ref(), DealFlowNode.ref()
    model.where(a.deal_flow_partner(b)).define(g.Edge.new(src=a, dst=b))
    return g


def define_deal_flow_centrality(g: Graph, with_communities: bool = True) -> None:
    """Which intermediaries actually bridge deal flow in our sectors.

    Betweenness counts, for every pair of firms, the share of shortest connections that pass through
    a firm: a high value means deals between otherwise separate founders and sponsors run through it.
    It is computed exactly (num_pivots = BETWEENNESS_PIVOTS, which exceeds any possible node count)
    and unnormalized, so it equals networkx betweenness_centrality(normalized=False). PageRank is a
    secondary "reach" column for display only. Intermediary.bridge_rank ranks intermediaries in the
    graph by betweenness (highest first, then name), which R09's CoverageGap rule reads. Louvain
    communities (optional) only color the explorer.
    """
    bc = g.betweenness_centrality(num_pivots=BETWEENNESS_PIVOTS)
    pr = g.pagerank()
    o, v = DealFlowNode.ref(), Float.ref()
    model.where(bc(o, v)).define(o.betweenness(v))
    o2, v2 = DealFlowNode.ref(), Float.ref()
    model.where(pr(o2, v2)).define(o2.pagerank(v2))
    model.where(Intermediary.betweenness).define(Intermediary.bridge_rank(
        rank(asc(0.0 - math.round(Intermediary.betweenness, BETWEENNESS_ROUND_DP)),
             asc(Intermediary.name), asc(Intermediary.id))))
    if with_communities:
        lab = g.louvain(randomization_seed=LOUVAIN_SEED)
        o3, l3 = DealFlowNode.ref(), Integer.ref()
        model.where(lab(o3, l3)).define(o3.flow_community(l3))


# ============================================================================================
# 3. Commercial graph (Q-CONFLICT, Q-ADDON backup)
# ============================================================================================
def build_commercial_graph() -> Graph:
    """The commercial network: companies linked when one supplies the other.

    Every company is a node. Each supplier-customer link (Company.supplies) becomes one undirected
    edge per pair, because a conflict or a shared counterparty matters whichever way the goods
    flow; the direction stays in the source data as evidence for R09's exposure text.
    """
    g = Graph(model, directed=False, weighted=False, node_concept=Company)
    a, b = Company.ref(), Company.ref()
    model.where(a.supplies(b), a.id < b.id).define(g.Edge.new(src=a, dst=b))
    model.where(a.supplies(b), b.id < a.id).define(g.Edge.new(src=b, dst=a))
    return g


def define_conflict_reach(g: Graph) -> None:
    """How many commercial links separate a bid subject from every other company.

    The bid subject is R09's ConflictSubject (the pipeline company at IOI prep). One single-sided
    distance call writes Company.commercial_hops(subject, company, hops) for every reachable
    company. R09 keeps our current holdings at 1 link (a conflict, or a same-fund link) or 2 links
    (a shared customer or supplier, informational); 3 links and beyond are outside the check.
    """
    model.where(ConflictSubject(Company)).define(_is_conflict_subject_node(Company))
    d_conf = g.distance(from_=_is_conflict_subject_node)
    s, c = Company.ref(), Company.ref()
    h = Integer.ref()
    # Contract field order is (subject, company, commercial_hops): see core.py reading.
    model.where(d_conf(s, c, h)).define(Company.commercial_hops(s, c, h))


def define_addon_similarity(g: Graph, with_communities: bool = True) -> None:
    """Backup (Q-ADDON): which companies share the most customers and suppliers with our platforms.

    Platforms are the companies Fund IV holds today. Jaccard similarity = shared commercial
    neighbors divided by all commercial neighbors of the pair; pairs with nothing in common are
    absent (not zero), and a platform is never compared with itself. Louvain communities (optional)
    color the commercial ecosystem in the explorer.
    """
    o, f, c = Ownership.ref(), BuyingFund.ref(), Company.ref()
    model.where(NorthwindHolding(o), o.fund(f), o.company(c)).define(_is_platform_node(c))
    jac = g.jaccard_similarity(from_=_is_platform_node)
    u, v, sc = Company.ref(), Company.ref(), Float.ref()
    model.where(jac(u, v, sc), u != v).define(Company.addon_similarity(u, v, sc))
    if with_communities:
        lab = g.louvain(randomization_seed=LOUVAIN_SEED)
        c2, l2 = Company.ref(), Integer.ref()
        model.where(lab(c2, l2)).define(c2.commercial_community(l2))


# ============================================================================================
# Build everything at import (definitions only; no query runs here)
# ============================================================================================
knows_graph = build_warm_path_graph()
define_seed_distances(knows_graph)
define_decision_maker_distances(knows_graph)
define_warm_paths()

deal_flow_graph = build_deal_flow_graph()
define_deal_flow_centrality(deal_flow_graph)

commercial_graph = build_commercial_graph()
define_conflict_reach(commercial_graph)
define_addon_similarity(commercial_graph)

GRAPHS = {"warm_path": knows_graph, "deal_flow": deal_flow_graph, "commercial": commercial_graph}


# ============================================================================================
# Validation: node and edge counts before any algorithm output is trusted
# ============================================================================================
def graph_sizes() -> dict[str, dict[str, int]]:
    """Node and edge counts of the three networks, read from the engine and logged.

    Run this before reading any algorithm output: a zero count means an edge rule matched nothing
    (for example, R09's Knows or DealFlowTransaction is empty), and every downstream answer would
    silently be empty too.
    """
    out: dict[str, dict[str, int]] = {}
    for name, g in GRAPHS.items():
        df = model.select(g.num_nodes().alias("nodes"), g.num_edges().alias("edges")).to_df()
        n = int(df["nodes"].iloc[0]) if len(df) else 0
        e = int(df["edges"].iloc[0]) if len(df) else 0
        out[name] = {"nodes": n, "edges": e}
        log.info("graph %s: %d nodes, %d edges", name, n, e)
        print(f"graphs: {name} graph has {n} nodes and {e} edges", flush=True)
    return out


def validate_graphs() -> dict[str, dict[str, int]]:
    """Fail fast unless every network is non-empty and betweenness can run exactly.

    Checks: each graph has nodes and edges; the deal-flow graph has no more nodes than
    BETWEENNESS_PIVOTS (otherwise betweenness would be sampled, not exact). Returns the sizes.
    """
    sizes = graph_sizes()
    for name, s in sizes.items():
        if s["nodes"] <= 0 or s["edges"] <= 0:
            raise AssertionError(f"graph {name} is empty: {s}")
    if sizes["deal_flow"]["nodes"] > BETWEENNESS_PIVOTS:
        raise AssertionError(
            f"deal-flow graph has {sizes['deal_flow']['nodes']} nodes > BETWEENNESS_PIVOTS={BETWEENNESS_PIVOTS}")
    return sizes


# ============================================================================================
# Rule catalog for the exporter (R13) and the explorer's rule panel
# ============================================================================================
def _doc(fn) -> str:
    import inspect as _inspect
    return _inspect.cleandoc(fn.__doc__ or "")


RULES = {
    "WARM_PATH": {
        "name": "Warm introduction path", "kind": "graph", "questions": ["Q-PATH", "FINALE"],
        "function": "define_warm_paths",
        "docstring": " ".join([_doc(build_warm_path_graph), _doc(define_seed_distances),
                               _doc(define_decision_maker_distances), _doc(define_warm_paths)]),
    },
    "SEED_DISTANCE": {
        "name": "Introductions from our nearest seed", "kind": "graph", "questions": ["Q-PATH", "FINALE"],
        "function": "define_seed_distances", "docstring": _doc(define_seed_distances),
    },
    "DEAL_FLOW": {
        "name": "Deal-flow bridges", "kind": "graph", "questions": ["Q-FLOW"],
        "function": "define_deal_flow_centrality",
        "docstring": " ".join([_doc(define_deal_flow_links), _doc(build_deal_flow_graph),
                               _doc(define_deal_flow_centrality)]),
    },
    "COMMERCIAL": {
        "name": "Commercial links and reach", "kind": "graph", "questions": ["Q-CONFLICT", "Q-ADDON"],
        "function": "define_conflict_reach",
        "docstring": " ".join([_doc(build_commercial_graph), _doc(define_conflict_reach)]),
    },
    "ADDON_SIMILARITY": {
        "name": "Add-on similarity (backup)", "kind": "graph", "questions": ["Q-ADDON"],
        "function": "define_addon_similarity", "docstring": _doc(define_addon_similarity),
    },
}

__all__ = [
    "knows_graph", "deal_flow_graph", "commercial_graph", "GRAPHS", "RULES", "graph_sizes", "validate_graphs",
    "WarmPathCandidate", "DealFlowNode", "MAX_RANKED_PATHS", "PATH_SCOPE_MIN_SCORE",
]
