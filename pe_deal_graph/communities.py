"""Communities and their best-connected members, at any scale (no dependency on core.py).

The question: "who are the best-connected people inside each group?" Louvain finds the groups;
betweenness inside a group says who the routes between its other members run through.

Why two modes
    Exact betweenness runs one search per person and keeps a row per (pivot, reachable person), so
    its cost grows with the SQUARE of each community's size. With one Louvain level communities are
    a few dozen people and exact is cheap; with several levels they reach thousands and exact took
    49 minutes at 100K people and never finished at 10M.

    ``num_pivots=None`` (default) keeps the original behaviour: exact everywhere.

    ``num_pivots=K`` switches to the hybrid: communities of at most ``exact_up_to`` members are still
    scored exactly (cheap, and sampling a 30-person group would be noise); larger communities are
    scored from K sampled pivots drawn only from their own members. Sampled scores are estimates:
    use them to rank people inside a community, not as exact values.

Usage
    labels, scores, sampled = community_connectors(model, Person, graph, max_levels=5,
                                                   randomization_seed=7, num_pivots=2000)
    p, c, s = Person.ref(), Integer.ref(), Float.ref()
    model.where(labels(p, c), scores(p, s)).select(p.id, c, s)
"""

from __future__ import annotations

import itertools

from relationalai.semantics import Float, Integer
from relationalai.semantics.reasoners.graph import Graph
from relationalai.semantics.std import aggregates as aggs

DEFAULT_EXACT_UP_TO = 200   # communities up to this size are always scored exactly in the hybrid
_names = itertools.count(1)  # helper relations need unique names when called more than once per model


def community_connectors(model, node_concept, graph, *, max_levels: int = 1, randomization_seed: int = 42,
                         exact_pivots: int, num_pivots: int | None = None,
                         exact_up_to: int = DEFAULT_EXACT_UP_TO):
    """Louvain labels plus betweenness inside each community.

    ``graph`` is an undirected, unweighted Graph whose node concept is ``node_concept``.
    ``exact_pivots`` must be at least the number of people (pivots >= nodes means exact Brandes).
    Returns ``(labels, scores, sampled)``: ``labels(node, community)``, ``scores(node, betweenness)``
    and the unary ``sampled(node)`` marking people whose score is an estimate (empty when exact).
    """
    for name, value, low in (("max_levels", max_levels, 1), ("randomization_seed", randomization_seed, 0),
                             ("exact_pivots", exact_pivots, 1), ("exact_up_to", exact_up_to, 1)):
        if type(value) is not int or value < low:
            raise ValueError(f"{name} must be an integer >= {low}")
    if num_pivots is not None and (type(num_pivots) is not int or num_pivots < 1):
        raise ValueError("num_pivots must be a positive integer or None")
    tag = next(_names)
    labels = graph.louvain(max_levels=max_levels, randomization_seed=randomization_seed)
    scores = model.Relationship(f"{node_concept:node} has internal betweenness {Float:score} in run {tag}")
    sampled = model.Relationship(f"{node_concept:node} has a sampled betweenness in run {tag}")
    a, b, label = node_concept.ref(), node_concept.ref(), Integer.ref()

    if num_pivots is None:
        # Dropping the links that cross communities leaves one separate subgraph per community, so
        # betweenness on that graph only counts routes inside each community.
        inside = Graph(model, directed=False, weighted=False, node_concept=node_concept)
        model.where(graph.Edge.src(a), graph.Edge.dst(b), labels(a, label), labels(b, label)).define(
            inside.Edge.new(src=a, dst=b))
        exact = inside.betweenness_centrality(num_pivots=exact_pivots)
        n, v = node_concept.ref(), Float.ref()
        model.where(exact(n, v)).define(scores(n, v))
        return labels, scores, sampled

    # Hybrid: split people by the size of their community.
    size = model.Relationship(f"community {Integer:label} has {Integer:members} members in run {tag}")
    m, c = node_concept.ref(), Integer.ref()
    model.where(labels(m, c)).define(size(c, aggs.count(m).per(c)))
    SmallMember = model.Concept(f"SmallCommunityMember{tag}", extends=[node_concept])
    LargeMember = model.Concept(f"LargeCommunityMember{tag}", extends=[node_concept])
    p, lab, count = node_concept.ref(), Integer.ref(), Integer.ref()
    model.where(labels(p, lab), size(lab, count), count <= exact_up_to).define(SmallMember(p))
    model.where(labels(p, lab), size(lab, count), count > exact_up_to).define(LargeMember(p))

    small = Graph(model, directed=False, weighted=False, node_concept=SmallMember)
    large = Graph(model, directed=False, weighted=False, node_concept=LargeMember)
    for members, target in ((SmallMember, small), (LargeMember, large)):
        x, y, shared = members.ref(), members.ref(), Integer.ref()
        model.where(graph.Edge.src(x), graph.Edge.dst(y), labels(x, shared), labels(y, shared)).define(
            target.Edge.new(src=x, dst=y))
    exact = small.betweenness_centrality(num_pivots=exact_pivots)
    estimate = large.betweenness_centrality(num_pivots=num_pivots)
    s, sv = SmallMember.ref(), Float.ref()
    model.where(exact(s, sv)).define(scores(s, sv))
    g, gv = LargeMember.ref(), Float.ref()
    model.where(estimate(g, gv)).define(scores(g, gv), sampled(g))
    return labels, scores, sampled


__all__ = ["community_connectors", "DEFAULT_EXACT_UP_TO"]
