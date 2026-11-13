"""
Neighbourhood graph builder.

Given an anchor concept + instance ID, builds a GraphDTO representing
all instances reachable within `depth` hops across the relationships
defined in the parsed model.

The builder operates in two modes:

  1. **Schema mode** (no live connection):  builds the neighbourhood purely
     from the parsed model — concepts and relationships only, no data rows.
     Used for the Semantic View and unit tests.

  2. **Data mode** (requires a Snowflake executor):  resolves each hop to
     actual data rows.  The executor is an injected callable so that tests
     can pass a mock.

Executor contract
-----------------
    executor(sql: str) -> list[dict[str, Any]]

The executor should run the SQL against Snowflake and return a list of
row dicts.  The FastAPI layer provides a real executor via the RAI client;
tests inject a stub.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import networkx as nx

from parser.model_parser import ConceptDef, ParsedModel, RelationshipDef
from rai.instance_query import (
    GraphDTO, GraphEdge, GraphNode, QueryPlanner,
    instance_to_node, row_to_instance, _snake,
)


# ── Executor type alias ───────────────────────────────────────────────────────

Executor = Callable[[str], list[dict[str, Any]]]


# ── Schema-level graph (no data) ──────────────────────────────────────────────

def build_semantic_graph(parsed_model: ParsedModel) -> GraphDTO:
    """
    Build the ontology/schema graph — one node per concept, one edge per
    relationship direction.  No data rows involved.

    This is the Semantic View graph.
    """
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    seen_edges: set[str] = set()

    for concept in parsed_model.concepts:
        nodes.append(GraphNode(
            id=concept.name,
            concept=concept.name,
            label=concept.name,
            attributes={
                "source_table": concept.source_table or "",
                "identify_by": [f["name"] for f in concept.identify_by],
                "property_count": len(concept.properties),
                "computed_property_count": len(concept.computed_properties),
                "relationship_count": len(concept.relationships),
            },
        ))

    for rel in parsed_model.relationships:
        for target_name in rel.target_concepts:
            edge_id = f"{rel.source_concept}-{rel.short_name}-{target_name}"
            if edge_id in seen_edges:
                continue
            seen_edges.add(edge_id)
            edges.append(GraphEdge(
                id=edge_id,
                source=rel.source_concept,
                target=target_name,
                relationship=rel.short_name,
                label=rel.label,
            ))

    return GraphDTO(nodes=nodes, edges=edges)


# ── Data-level neighbourhood graph ────────────────────────────────────────────

@dataclass
class NeighbourhoodRequest:
    concept: str
    instance_id: Any        # PK value of the anchor instance
    depth: int = 1          # hops to traverse (1 = direct neighbours)
    max_nodes: int = 150    # hard cap to avoid browser overload


def build_neighbourhood_graph(
    request: NeighbourhoodRequest,
    parsed_model: ParsedModel,
    executor: Executor,
) -> GraphDTO:
    """
    BFS from an anchor instance across all outbound relationships to depth N.

    Each hop:
      1. Finds all relationships on the current concept.
      2. For each relationship with a known target concept + resolvable FK,
         queries the target table.
      3. Adds result rows as nodes + edges to the graph.

    Returns a GraphDTO.
    """
    planner = QueryPlanner(parsed_model)
    concept_map: dict[str, ConceptDef] = {
        c.name: c for c in parsed_model.concepts
    }

    nodes: dict[str, GraphNode] = {}
    edges: dict[str, GraphEdge] = {}

    # BFS queue: (concept_name, instance_id, current_depth)
    queue: deque[tuple[str, Any, int]] = deque()
    visited: set[str] = set()

    # Seed the anchor
    anchor_node_id = f"{request.concept}:{request.instance_id}"
    anchor_concept = concept_map[request.concept]

    # Fetch anchor row using the real PK column from the parsed model.
    # Falls back to a synthetic node on any error.
    anchor_node: Optional[GraphNode] = None
    pk_col = anchor_concept.pk_col or _snake(
        anchor_concept.identify_by[0]["name"]
    ) if anchor_concept.identify_by else None

    try:
        if pk_col:
            anchor_rows = executor(
                planner.fetch_sql(
                    request.concept,
                    filters={pk_col: request.instance_id},
                    limit=1,
                )
            )
        else:
            anchor_rows = []
        if anchor_rows:
            anchor_inst = row_to_instance(anchor_concept, anchor_rows[0])
            anchor_node = instance_to_node(anchor_inst)
            anchor_node.id = anchor_node_id
    except Exception:
        pass  # fall through to synthetic node

    if anchor_node is None:
        anchor_node = GraphNode(
            id=anchor_node_id,
            concept=request.concept,
            label=f"{request.concept} #{request.instance_id}",
        )
    nodes[anchor_node_id] = anchor_node

    queue.append((request.concept, request.instance_id, 0))
    visited.add(anchor_node_id)

    while queue:
        if len(nodes) >= request.max_nodes:
            break

        concept_name, instance_id, depth = queue.popleft()
        if depth >= request.depth:
            continue

        concept = concept_map.get(concept_name)
        if not concept:
            continue

        for rel in concept.relationships:
            if not rel.target_concepts:
                continue

            for target_name in rel.target_concepts:
                if target_name not in concept_map:
                    continue

                sql = planner.relationship_join_sql(
                    concept_name, instance_id, rel.short_name
                )
                if not sql:
                    continue

                try:
                    rows = executor(sql)
                except Exception:
                    continue

                target_concept = concept_map[target_name]

                for row in rows:
                    if len(nodes) >= request.max_nodes:
                        break

                    inst = row_to_instance(target_concept, row)
                    target_node = instance_to_node(inst)

                    if target_node.id not in nodes:
                        nodes[target_node.id] = target_node

                    # Source node id for this hop
                    source_node_id = f"{concept_name}:{instance_id}"
                    edge_id = f"{source_node_id}->{rel.short_name}->{target_node.id}"
                    if edge_id not in edges:
                        edges[edge_id] = GraphEdge(
                            id=edge_id,
                            source=source_node_id,
                            target=target_node.id,
                            relationship=rel.short_name,
                            label=rel.label,
                        )

                    if target_node.id not in visited:
                        visited.add(target_node.id)
                        target_pk = next(iter(inst.id_fields.values()), None)
                        if target_pk is not None:
                            queue.append((target_name, target_pk, depth + 1))

    return GraphDTO(nodes=list(nodes.values()), edges=list(edges.values()))


# ── NetworkX conversion (for graph algorithms) ───────────────────────────────

def graph_dto_to_nx(dto: GraphDTO) -> nx.MultiDiGraph:
    """
    Convert a GraphDTO to a NetworkX MultiDiGraph.

    MultiDiGraph is required because a concept pair can be connected by more
    than one relationship (e.g. Barista → Location via barista_shift AND
    barista_home_location).
    """
    g = nx.MultiDiGraph()
    for node in dto.nodes:
        g.add_node(node.id, concept=node.concept, label=node.label, **node.attributes)
    for edge in dto.edges:
        g.add_edge(
            edge.source, edge.target,
            key=edge.id,
            relationship=edge.relationship,
            label=edge.label,
        )
    return g


def nx_to_graph_dto(g: nx.MultiDiGraph) -> GraphDTO:
    """Convert a NetworkX MultiDiGraph back to GraphDTO."""
    nodes = [
        GraphNode(
            id=n,
            concept=data.get("concept", ""),
            label=data.get("label", n),
            attributes={k: v for k, v in data.items() if k not in ("concept", "label")},
        )
        for n, data in g.nodes(data=True)
    ]
    edges = [
        GraphEdge(
            id=key if isinstance(key, str) else f"{u}->{v}",
            source=u,
            target=v,
            relationship=data.get("relationship", ""),
            label=data.get("label", ""),
        )
        for u, v, key, data in g.edges(data=True, keys=True)
    ]
    return GraphDTO(nodes=nodes, edges=edges)


def find_shortest_path(dto: GraphDTO, source_id: str, target_id: str) -> Optional[GraphDTO]:
    """
    Find the shortest path between two node IDs and return it as a GraphDTO.
    Returns None if no path exists.
    """
    g = graph_dto_to_nx(dto)
    try:
        path_nodes = nx.shortest_path(g.to_undirected(), source_id, target_id)
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None

    path_node_set = set(path_nodes)
    filtered_nodes = [n for n in dto.nodes if n.id in path_node_set]
    filtered_edges = [
        e for e in dto.edges
        if e.source in path_node_set and e.target in path_node_set
    ]
    return GraphDTO(nodes=filtered_nodes, edges=filtered_edges)
