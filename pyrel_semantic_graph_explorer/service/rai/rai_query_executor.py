"""
RAI Query Executor — prototype for querying the semantic layer via the
RelationalAI Python library rather than hand-crafted SQL.

Why this matters
----------------
The static AST parser + raw SQL approach works for simple concepts, but it
cannot express:

  - Computed/derived properties  (profit_margin, years_of_service, ...)
  - Business-rule predicates     (valid_hourly_wage, violates_overtime_limit)
  - Complex relationship traversals across multiple hops
  - Aggregations defined in the model

The RelationalAI library executes all of this server-side through the
reasoner, and returns results as a pandas DataFrame.

How it works
------------
1. Load the model source file into a live Python namespace using exec().
   This gives us the actual model object + concept variables exactly as
   the model author wrote them.

2. Attach the model to a live RAI engine using raiconfig credentials.

3. Use the PyREL query DSL — select(), where(), filter_by() — to query
   concepts and their relationships, including computed properties.

4. Convert the resulting DataFrame into the same GraphDTO / InstancePage
   DTOs used by the rest of the service, so no API changes are needed.

Prototype status
----------------
This file is a working design prototype.  It shows the intended architecture
and query patterns.  To make it fully operational you need:

  - relationalai SDK installed:  pip install relationalai
  - A running RAI engine in Snowflake (the model defines which one via
    model = Model("name", engine="engine_name"))
  - The model file available at startup (same as today)

Usage (drop-in alongside existing QueryPlanner)
-----------------------------------------------
    from rai.rai_query_executor import RaiQueryExecutor
    from rai.client import load_rai_config

    config = load_rai_config()
    executor = RaiQueryExecutor.from_model_file(
        model_path="/path/to/model.py",
        rai_config=config,
    )

    # Fetch paginated instances
    page = executor.fetch_instances("Barista", limit=50, offset=0)

    # Fetch with computed properties included
    page = executor.fetch_instances(
        "Barista",
        include_computed=["years_of_service", "valid_hourly_wage"],
        limit=50,
    )

    # Neighbourhood graph via relationship traversal
    graph = executor.fetch_neighbourhood("Barista", pk_value=5, depth=1)
"""
from __future__ import annotations

import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from parser.model_parser import ConceptDef, ParsedModel
from rai.client import RaiConfig
from rai.instance_query import GraphDTO, GraphEdge, GraphNode, InstancePage, InstanceRow


# ── Model namespace loader ────────────────────────────────────────────────────

def load_model_namespace(model_path: str | Path) -> dict[str, Any]:
    """
    Execute a PyREL model file in an isolated namespace and return it.

    This gives us live concept variables (Barista, Location, …) and the
    model object itself, exactly as the author wrote them.  All side-effects
    (Table registrations, define() calls, @define extensions) run normally
    because the relationalai SDK is imported.

    Returns a dict with all module-level names from the file, including:
      namespace["model"]    → the Model object
      namespace["Barista"]  → the Barista Concept object
      … etc.
    """
    source = Path(model_path).read_text()
    namespace: dict[str, Any] = {"__file__": str(model_path)}
    exec(compile(source, str(model_path), "exec"), namespace)
    return namespace


# ── Executor ─────────────────────────────────────────────────────────────────

class RaiQueryExecutor:
    """
    Query the semantic layer using the RelationalAI Python library.

    This is the high-fidelity alternative to QueryPlanner + raw SQL.
    It delegates all computation to the RAI reasoner, which means:

      - Computed properties are evaluated correctly
      - Relationship traversals use the model's defined join logic
      - Business rules (valid_*, violates_*) are available for filtering
    """

    def __init__(self, namespace: dict[str, Any], parsed_model: ParsedModel):
        self._ns = namespace
        self._model = namespace["model"]          # relationalai.semantics.Model
        self._parsed = parsed_model               # for metadata / fallback

    @classmethod
    def from_model_file(
        cls,
        model_path: str | Path,
        parsed_model: ParsedModel,
    ) -> "RaiQueryExecutor":
        """
        Load the model file and return an executor.

        The relationalai SDK must be installed and a raiconfig.toml must be
        discoverable so the SDK can connect to the RAI engine.
        """
        ns = load_model_namespace(model_path)
        return cls(ns, parsed_model)

    # ── Concept resolution ────────────────────────────────────────────────

    def _concept_var(self, concept_name: str) -> Any:
        """
        Return the live Concept object from the model namespace.

        e.g. "Barista" → namespace["Barista"]  (a relationalai Concept)
        """
        obj = self._ns.get(concept_name)
        if obj is None:
            raise ValueError(
                f"Concept '{concept_name}' not found in model namespace. "
                f"Available names: {[k for k in self._ns if k[0].isupper()]}"
            )
        return obj

    # ── Instance fetching ─────────────────────────────────────────────────

    def fetch_instances(
        self,
        concept_name: str,
        limit: int = 50,
        offset: int = 0,
        search: Optional[str] = None,
        include_computed: Optional[list[str]] = None,
    ) -> InstancePage:
        """
        Fetch paginated instances for a concept using the PyREL DSL.

        Includes scalar properties from the model.  Optionally includes
        computed/derived properties (e.g. years_of_service, profit_margin).

        PyREL does not natively support LIMIT/OFFSET, so we use rank-based
        pagination: rank all instances, then filter to the desired window.

        Example generated query (pseudo-DSL):

            select(
                Barista.barista_id,
                Barista.profile[full_name],
                Barista.profile[hourly_wage],
                Barista.years_of_service,      # computed
                rank(Barista).per(Barista),
            ).where(
                rank(Barista).per(Barista) > offset,
                rank(Barista).per(Barista) <= offset + limit,
            ).to_df()
        """
        try:
            from relationalai.semantics import select, where
            from relationalai.semantics.std.aggregates import rank
        except ImportError as e:
            raise RuntimeError(
                "relationalai SDK not installed. "
                "Run: pip install relationalai"
            ) from e

        concept = self._concept_var(concept_name)
        concept_def = self._parsed_concept(concept_name)

        # Build the select columns: identify_by + all scalar relationship groups
        #
        # In PyREL, scalar properties live on relationship groups accessed via
        # dot notation:
        #   Barista.profile[String:full_name]   → barista.profile.full_name
        #   Barista.performance_metrics[Float:avg_drinks_per_hour]
        #
        # For the prototype we select the concept PK + profile relationship.
        # A full implementation would iterate concept_def.relationships.
        pk_col = concept_def.pk_col or "id"
        select_cols = [getattr(concept, pk_col, concept)]

        # Add scalar properties from relationship groups
        for rel in concept_def.relationships:
            for prop in rel.scalar_properties:
                # Access: concept.rel_attr_name  (returns the relationship fragment)
                rel_fragment = getattr(concept, rel.name, None)
                if rel_fragment is not None:
                    select_cols.append(rel_fragment)

        # Add requested computed properties
        for comp_name in (include_computed or []):
            comp_fragment = getattr(concept, comp_name, None)
            if comp_fragment is not None:
                select_cols.append(comp_fragment)

        # Rank for pagination
        r = rank(concept).per(concept)
        select_cols.append(r)

        # Execute with pagination window
        df: pd.DataFrame = (
            select(*select_cols)
            .where(r > offset, r <= offset + limit)
            .to_df()
        )

        return self._df_to_instance_page(df, concept_def, limit, offset)

    # ── Instance fetching by PK ───────────────────────────────────────────

    def fetch_instance_by_pk(
        self,
        concept_name: str,
        pk_value: Any,
    ) -> Optional[InstanceRow]:
        """
        Fetch a single instance by its primary key value.

        Uses filter_by() which translates to a server-side equality predicate.

        Example:
            Barista.filter_by(barista_id=5)
        """
        try:
            from relationalai.semantics import select, where
        except ImportError as e:
            raise RuntimeError("relationalai SDK not installed.") from e

        concept = self._concept_var(concept_name)
        concept_def = self._parsed_concept(concept_name)
        pk_col = concept_def.pk_col

        if not pk_col:
            return None

        # filter_by kwarg must match the identify_by label used in the model
        anchor = concept.filter_by(**{pk_col: pk_value})
        df = select(anchor).to_df()

        if df.empty:
            return None
        rows = self._df_to_instance_page(df, concept_def, limit=1, offset=0).rows
        return rows[0] if rows else None

    # ── Neighbourhood / relationship traversal ────────────────────────────

    def fetch_neighbourhood(
        self,
        concept_name: str,
        pk_value: Any,
        depth: int = 1,
        max_nodes: int = 150,
    ) -> GraphDTO:
        """
        Build a neighbourhood graph using PyREL relationship traversal.

        This is fundamentally more powerful than the SQL JOIN approach because:
          - Multi-hop traversals work naturally via chained dot notation
          - Computed properties on related concepts are available
          - The reasoner handles cardinality and deduplication

        Example for Barista depth=1 (pseudo-DSL):

            barista = Barista.filter_by(barista_id=5)

            # Hop 1a: Barista → Shift (via barista_shift)
            shift = barista.shift[Shift]

            # Hop 1b: Barista → Location (via barista_home_location)
            location = barista.home_location[Location]

            select(
                barista.barista_id, barista.profile[full_name],
                shift.shift_id, shift.shift_date,
                location.location_id, location.profile[store_name],
            ).to_df()

        For depth > 1, continue chaining from each discovered concept.
        """
        try:
            from relationalai.semantics import select
        except ImportError as e:
            raise RuntimeError("relationalai SDK not installed.") from e

        concept = self._concept_var(concept_name)
        concept_def = self._parsed_concept(concept_name)
        pk_col = concept_def.pk_col

        if not pk_col:
            return GraphDTO(nodes=[], edges=[])

        # Anchor instance
        anchor = concept.filter_by(**{pk_col: pk_value})
        anchor_node_id = f"{concept_name}:{pk_value}"

        nodes: dict[str, GraphNode] = {
            anchor_node_id: GraphNode(
                id=anchor_node_id,
                concept=concept_name,
                label=f"{concept_name} #{pk_value}",
            )
        }
        edges: dict[str, GraphEdge] = {}

        # BFS over relationships using PyREL dot-notation traversal
        queue = [(concept_name, anchor, anchor_node_id, 0)]

        while queue and len(nodes) < max_nodes:
            src_concept_name, src_fragment, src_node_id, current_depth = queue.pop(0)
            if current_depth >= depth:
                continue

            src_def = self._parsed_concept(src_concept_name)

            for rel in src_def.relationships:
                for target_name in rel.target_concepts:
                    target_concept = self._ns.get(target_name)
                    if target_concept is None:
                        continue

                    target_def = self._parsed_concept(target_name)
                    rel_fragment = getattr(src_fragment, rel.name, None)
                    if rel_fragment is None:
                        continue

                    # Traverse: src.rel_name[TargetConcept]
                    # This returns a fragment representing related target instances
                    traversed = rel_fragment[target_concept]
                    target_pk_col = target_def.pk_col

                    try:
                        if target_pk_col:
                            df = select(
                                getattr(src_fragment, pk_col or "id"),
                                getattr(traversed, target_pk_col),
                            ).to_df()
                        else:
                            df = select(src_fragment, traversed).to_df()
                    except Exception:
                        continue

                    for _, row in df.iterrows():
                        if len(nodes) >= max_nodes:
                            break

                        target_pk_val = row.get(target_pk_col) if target_pk_col else None
                        target_node_id = f"{target_name}:{target_pk_val}"

                        if target_node_id not in nodes:
                            nodes[target_node_id] = GraphNode(
                                id=target_node_id,
                                concept=target_name,
                                label=f"{target_name} #{target_pk_val}",
                                attributes=dict(row),
                            )

                        edge_id = f"{src_node_id}->{rel.short_name}->{target_node_id}"
                        if edge_id not in edges:
                            edges[edge_id] = GraphEdge(
                                id=edge_id,
                                source=src_node_id,
                                target=target_node_id,
                                relationship=rel.short_name,
                                label=rel.label,
                            )

                        if target_node_id not in {n for n in nodes if n != target_node_id}:
                            target_anchor = target_concept.filter_by(
                                **{target_pk_col: target_pk_val}
                            ) if target_pk_col else traversed
                            queue.append((
                                target_name, target_anchor, target_node_id,
                                current_depth + 1,
                            ))

        return GraphDTO(nodes=list(nodes.values()), edges=list(edges.values()))

    # ── Aggregation queries (new capability vs SQL approach) ──────────────

    def aggregate_concept(
        self,
        concept_name: str,
        group_by: str,
        metric: str,
        agg_fn: str = "count",
    ) -> pd.DataFrame:
        """
        Run an aggregation query using the PyREL aggregation DSL.

        This enables things like:
          - Count of Orders per Location
          - Average hourly_wage per Barista role
          - Sum of total_revenue per LocationDailyMetrics date

        These would require complex SQL subqueries to write by hand but are
        natural in the PyREL DSL.

        Example:
            executor.aggregate_concept(
                "Order", group_by="location_id", metric="order_id", agg_fn="count"
            )

        Generated query (pseudo-DSL):
            select(
                Order.location_id,
                count(Order.order_id).per(Order.location_id),
            ).to_df()
        """
        try:
            from relationalai.semantics import select
            from relationalai.semantics.std import aggregates as aggs
        except ImportError as e:
            raise RuntimeError("relationalai SDK not installed.") from e

        concept = self._concept_var(concept_name)
        agg_func = getattr(aggs, agg_fn, None)
        if agg_func is None:
            raise ValueError(f"Unknown aggregation function: {agg_fn}")

        group_fragment = getattr(concept, group_by)
        metric_fragment = getattr(concept, metric)

        return select(
            group_fragment,
            agg_func(metric_fragment).per(group_fragment),
        ).to_df()

    # ── Query with computed properties (new capability) ───────────────────

    def fetch_instances_with_computed(
        self,
        concept_name: str,
        computed_properties: list[str],
        filter_computed: Optional[dict[str, Any]] = None,
        limit: int = 50,
    ) -> pd.DataFrame:
        """
        Fetch instances including computed/derived properties.

        This is the key advantage over raw SQL: computed properties like
        profit_margin, years_of_service, violates_overtime_limit are
        evaluated by the reasoner and returned alongside raw data.

        Example — baristas who violate overtime and their years_of_service:

            executor.fetch_instances_with_computed(
                "Barista",
                computed_properties=["years_of_service", "valid_hourly_wage"],
                filter_computed={"valid_hourly_wage": True},
            )

        Generated query (pseudo-DSL):
            select(
                Barista.barista_id,
                Barista.profile[full_name],
                Barista.years_of_service,
                Barista.valid_hourly_wage,
            ).where(
                Barista.valid_hourly_wage == True,
            ).to_df()
        """
        try:
            from relationalai.semantics import select, where
        except ImportError as e:
            raise RuntimeError("relationalai SDK not installed.") from e

        concept = self._concept_var(concept_name)
        concept_def = self._parsed_concept(concept_name)
        pk_col = concept_def.pk_col

        # Base columns: PK + computed properties requested
        select_cols = []
        if pk_col:
            pk_fragment = getattr(concept, pk_col, None)
            if pk_fragment:
                select_cols.append(pk_fragment)

        for prop_name in computed_properties:
            frag = getattr(concept, prop_name, None)
            if frag is not None:
                select_cols.append(frag)

        if not select_cols:
            return pd.DataFrame()

        # Apply computed property filters if requested
        where_clauses = []
        for prop_name, expected_val in (filter_computed or {}).items():
            frag = getattr(concept, prop_name, None)
            if frag is not None:
                where_clauses.append(frag == expected_val)

        query = select(*select_cols)
        if where_clauses:
            query = query.where(*where_clauses)

        return query.to_df()

    # ── Helpers ───────────────────────────────────────────────────────────

    def _parsed_concept(self, name: str) -> ConceptDef:
        for c in self._parsed.concepts:
            if c.name == name:
                return c
        raise ValueError(f"Concept '{name}' not found in parsed model.")

    def _df_to_instance_page(
        self,
        df: pd.DataFrame,
        concept_def: ConceptDef,
        limit: int,
        offset: int,
    ) -> InstancePage:
        """Convert a pandas DataFrame from to_df() into an InstancePage."""
        pk_col = concept_def.pk_col
        rows = []
        for _, row in df.iterrows():
            row_dict = row.to_dict()
            id_fields = {pk_col: row_dict.get(pk_col)} if pk_col else {}
            label = (
                str(row_dict.get("full_name") or row_dict.get("store_name")
                    or row_dict.get("item_name") or row_dict.get(pk_col, "?"))
            )
            attributes = {k: v for k, v in row_dict.items() if k != pk_col}
            rows.append(InstanceRow(
                concept=concept_def.name,
                id_fields=id_fields,
                label=label,
                attributes=attributes,
            ))
        return InstancePage(
            concept=concept_def.name,
            total_count=None,
            rows=rows,
            limit=limit,
            offset=offset,
        )


# ── Integration note ──────────────────────────────────────────────────────────
#
# To wire this into main.py as a drop-in alongside the existing QueryPlanner:
#
#   # In lifespan():
#   try:
#       _state.rai_executor = RaiQueryExecutor.from_model_file(
#           model_path, _state.parsed_model
#       )
#   except Exception as e:
#       print(f"[startup] RAI executor not available: {e}")
#
#   # In get_instances():
#   if _state.rai_executor and request.args.get("use_rai"):
#       page = _state.rai_executor.fetch_instances(concept, limit=limit, offset=offset,
#                                                   include_computed=["years_of_service"])
#   else:
#       # existing SQL path
#       ...
#
# This allows gradual migration: raw SQL for simple queries, RAI for complex ones.
