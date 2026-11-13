"""
Instance query service.

Fetches actual data rows for a concept from Snowflake via the RAI SDK,
using the parsed model to know which table to read and which columns to select.

The service is designed so that the RAI SDK is only imported when a live
query is actually executed.  All building/planning logic works offline and
is fully testable without a Snowflake connection.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from parser.model_parser import ConceptDef, ParsedModel


# ── DTOs ──────────────────────────────────────────────────────────────────────

@dataclass
class InstanceRow:
    """A single data row for a concept instance."""
    concept: str
    id_fields: dict[str, Any]          # e.g. {"location_id": 5}
    label: str                          # human-readable identifier string
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class InstancePage:
    concept: str
    total_count: Optional[int]          # None if count query not yet run
    rows: list[InstanceRow]
    limit: int
    offset: int


@dataclass
class GraphNode:
    id: str                             # "{concept}:{pk_value}"
    concept: str
    label: str
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphEdge:
    id: str
    source: str                         # GraphNode.id
    target: str                         # GraphNode.id
    relationship: str                   # short_name
    label: str                          # natural language label


@dataclass
class GraphDTO:
    """Generic graph payload consumed by the frontend."""
    nodes: list[GraphNode]
    edges: list[GraphEdge]


# ── Query planner (offline, testable) ─────────────────────────────────────────

class QueryPlanner:
    """
    Builds Snowflake SQL query strings from a parsed model.

    All methods are pure (no I/O) so they can be tested without a connection.
    """

    def __init__(self, parsed_model: ParsedModel):
        self._model = parsed_model
        self._concept_map: dict[str, ConceptDef] = {
            c.name: c for c in parsed_model.concepts
        }

    def concept_names(self) -> list[str]:
        return list(self._concept_map)

    def get_concept(self, name: str) -> ConceptDef:
        if name not in self._concept_map:
            raise ValueError(
                f"Unknown concept '{name}'. "
                f"Available: {list(self._concept_map)}"
            )
        return self._concept_map[name]

    def count_sql(self, concept_name: str) -> str:
        """SELECT COUNT(*) FROM source_table"""
        concept = self.get_concept(concept_name)
        if not concept.source_table:
            raise ValueError(f"Concept '{concept_name}' has no source table.")
        return f"SELECT COUNT(*) AS cnt FROM {concept.source_table}"

    def fetch_sql(
        self,
        concept_name: str,
        limit: int = 50,
        offset: int = 0,
        filters: Optional[dict[str, Any]] = None,
        search: Optional[str] = None,
    ) -> str:
        """
        Build a SELECT with the identify_by columns plus the first property
        group columns, with optional WHERE filters and LIKE search.
        """
        concept = self.get_concept(concept_name)
        if not concept.source_table:
            raise ValueError(f"Concept '{concept_name}' has no source table.")

        sql = f"SELECT * FROM {concept.source_table}"

        where_clauses: list[str] = []

        if filters:
            for col, val in filters.items():
                safe_col = re.sub(r"[^a-zA-Z0-9_]", "", col)
                if isinstance(val, str):
                    escaped = val.replace("'", "''")
                    where_clauses.append(f'"{safe_col}" = \'{escaped}\'')
                elif isinstance(val, (int, float)):
                    where_clauses.append(f'"{safe_col}" = {val}')
                elif isinstance(val, bool):
                    where_clauses.append(f'"{safe_col}" = {str(val).upper()}')

        if search:
            # Full-text ILIKE search across PK columns (use pk_col if available)
            pk_col = concept.pk_col or (
                _snake(concept.identify_by[0]["name"]) if concept.identify_by else None
            )
            if pk_col:
                escaped_search = search.replace(chr(39), chr(39) * 2)
                where_clauses.append(
                    f'CAST("{pk_col}" AS VARCHAR) ILIKE \'%{escaped_search}%\''
                )

        if where_clauses:
            sql += " WHERE " + " AND ".join(where_clauses)

        sql += f" LIMIT {int(limit)} OFFSET {int(offset)}"
        return sql

    def relationship_join_sql(
        self,
        source_concept: str,
        source_id_value: Any,
        relationship_short_name: str,
    ) -> Optional[str]:
        """
        Build a SQL query to fetch instances connected to a given source
        instance via a specific relationship, using FK columns in the source table.

        Returns None if the relationship cannot be resolved to a direct FK.
        """
        source = self.get_concept(source_concept)
        if not source.source_table:
            return None

        # Find the relationship on the source concept
        rel = next(
            (r for r in source.relationships
             if r.short_name == relationship_short_name),
            None,
        )
        if not rel or not rel.target_concepts:
            return None

        target_concept_name = rel.target_concepts[0]
        if target_concept_name not in self._concept_map:
            return None
        target = self._concept_map[target_concept_name]
        if not target.source_table:
            return None

        # Resolve column names from the parsed model (preferred) or fall back to
        # deriving them from semantic label names.
        source_pk_col = (
            rel.source_pk_col
            or source.pk_col
            or (_snake(source.identify_by[0]["name"]) if source.identify_by else None)
        )
        if not source_pk_col:
            return None

        fk_col = rel.fk_cols.get(target_concept_name)
        if not fk_col:
            # Fall back: derive FK col from target's PK label
            if not target.identify_by:
                return None
            fk_col = _snake(target.identify_by[0]["name"])

        target_pk_col = target.pk_col or (
            _snake(target.identify_by[0]["name"]) if target.identify_by else None
        )
        if not target_pk_col:
            return None

        if isinstance(source_id_value, str):
            pk_val = f"'{source_id_value.replace(chr(39), chr(39)*2)}'"
        else:
            pk_val = str(source_id_value)

        # If the relationship's FK lives in a table OTHER than the source concept's own
        # table (e.g. Barista→Shift where the barista_id FK is in SHIFTS, not BARISTAS),
        # query that table directly instead of doing a JOIN.
        source_filter_table = getattr(rel, 'source_filter_table', None)
        if source_filter_table and source_filter_table != source.source_table:
            return f'SELECT * FROM {source_filter_table} WHERE "{source_pk_col}" = {pk_val}'

        # FK lives in source concept's own table → use JOIN
        return (
            f"SELECT t.* "
            f"FROM {target.source_table} t "
            f'JOIN {source.source_table} s ON s."{fk_col}" = t."{target_pk_col}" '
            f'WHERE s."{source_pk_col}" = {pk_val}'
        )


# ── Row → DTO mappers ─────────────────────────────────────────────────────────

def row_to_instance(concept: ConceptDef, row: dict[str, Any]) -> InstanceRow:
    """Convert a raw Snowflake row dict to an InstanceRow.

    Snowflake returns column names in UPPERCASE; model-derived names are
    lowercase_snake.  We do a case-insensitive lookup so both conventions work.
    """
    # Build a case-insensitive lookup once
    row_upper: dict[str, Any] = {k.upper(): v for k, v in row.items()}

    def _get(col: str) -> Any:
        return row_upper.get(col.upper())

    # Use pk_col from model if available (physical column name); fall back to derived
    if concept.pk_col and concept.identify_by:
        id_fields = {concept.pk_col: _get(concept.pk_col)}
    else:
        id_fields = {
            _snake(f["name"]): _get(_snake(f["name"]))
            for f in concept.identify_by
        }
    # Build a human-readable label from the most descriptive available column
    label = _build_label(concept, row_upper)
    attributes = {k: v for k, v in row.items() if k.upper() not in {k2.upper() for k2 in id_fields}}
    return InstanceRow(
        concept=concept.name,
        id_fields=id_fields,
        label=label,
        attributes=attributes,
    )


def instance_to_node(row: InstanceRow) -> GraphNode:
    pk_val = next(iter(row.id_fields.values()), "?")
    node_id = f"{row.concept}:{pk_val}"
    return GraphNode(
        id=node_id,
        concept=row.concept,
        label=row.label,
        attributes={**row.id_fields, **row.attributes},
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

_LABEL_CANDIDATES = [
    "name", "full_name", "store_name", "item_name", "title",
    "display_name", "email", "description",
]


def _build_label(concept: ConceptDef, row: dict[str, Any]) -> str:
    """Pick the most descriptive string value from a row as the node label.

    `row` may have either upper- or lower-case keys; comparison is case-insensitive.
    """
    row_upper = {k.upper(): v for k, v in row.items()}
    for col in _LABEL_CANDIDATES:
        val = row_upper.get(col.upper())
        if val:
            return str(val)
    # Fall back to the first identify_by column value
    if concept.identify_by:
        pk_col = _snake(concept.identify_by[0]["name"]).upper()
        val = row_upper.get(pk_col, "?")
        return f"{concept.name} #{val}"
    return concept.name


def _snake(name: str) -> str:
    """'Location ID' → 'location_id'"""
    return re.sub(r"\s+", "_", name.strip()).lower()


def _dedupe(cols: list[str]) -> list[str]:
    seen: set[str] = set()
    result = []
    for c in cols:
        if c not in seen:
            seen.add(c)
            result.append(c)
    return result
