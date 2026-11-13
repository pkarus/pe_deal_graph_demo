"""
AST-based parser for PyREL semantic layer model files.

Extracts concepts, relationships, properties, source tables, and computed
properties from a model .py file without executing it.
"""
import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class PropertyDef:
    name: str
    type: str  # "String" | "Float" | "Integer" | "Bool"
    relationship_group: str  # short_name of the Relationship it belongs to


@dataclass
class RelationshipDef:
    name: str          # attribute name on the concept (e.g. "at_location")
    short_name: str    # short_name= kwarg
    label: str         # natural language label parsed from the f-string
    source_concept: str
    target_concepts: list[str]   # one or more target concept names
    scalar_properties: list[PropertyDef]  # scalar fields carried on this edge
    source_filter_table: Optional[str] = None  # Snowflake table the source filter_by references
    source_pk_col: Optional[str] = None   # physical PK column in source table
    fk_cols: dict = field(default_factory=dict)  # target_concept → FK col in source table


@dataclass
class ComputedPropertyDef:
    name: str
    return_type: Optional[str]   # from the -> annotation if present
    docstring: Optional[str]


@dataclass
class ConceptDef:
    name: str
    identify_by: list[dict]          # [{"name": "Location ID", "type": "Integer"}, ...]
    source_table: Optional[str]       # fully qualified Snowflake table
    pk_col: Optional[str] = None      # physical PK column name, e.g. "barista_id"
    properties: list[PropertyDef] = field(default_factory=list)
    relationships: list[RelationshipDef] = field(default_factory=list)
    computed_properties: list[ComputedPropertyDef] = field(default_factory=list)


@dataclass
class ParsedModel:
    model_name: str
    source_tables: dict[str, str]       # logical_name -> "DB.SCHEMA.TABLE"
    concepts: list[ConceptDef]
    relationships: list[RelationshipDef]  # all relationships, flat


# ── Source preprocessor ───────────────────────────────────────────────────────

def _sanitize_source(source: str) -> str:
    """
    PyREL model files use multi-word identifiers with spaces in two positions
    that are illegal Python syntax:

      1. Keyword argument names:   filter_by(Menu Item ID=...)
      2. Attribute access chains:  .menu_items.Menu Item ID

    We replace spaces within these capitalized multi-word tokens with
    underscores so that ``ast.parse`` succeeds.  String literal content
    is left untouched because the patterns we target (capital-word sequences
    followed by ``=`` or preceded by ``.``) do not appear inside strings.
    """
    # Keyword arg names:  `Menu Item ID=`  →  `Menu_Item_ID=`
    source = re.sub(
        r'([A-Z][a-zA-Z0-9]*(?:\s+[A-Z][a-zA-Z0-9]*)+)(?=\s*=)',
        lambda m: m.group(0).replace(' ', '_'),
        source,
    )
    # Attribute accesses: `.Menu Item ID`  →  `.Menu_Item_ID`
    source = re.sub(
        r'(?<=\.)([A-Z][a-zA-Z0-9]*(?:\s+[A-Z][a-zA-Z0-9]*)+)',
        lambda m: m.group(0).replace(' ', '_'),
        source,
    )
    return source


# ── Helpers ───────────────────────────────────────────────────────────────────

# Matches e.g. {String:Item Name}, {Float:Retail Price}, {Integer:Prep Time (Seconds)}, {Bool:Is Active}
_SCALAR_RE = re.compile(r"\{(String|Float|Integer|Bool):([^}]+)\}")

# Matches concept placeholders like {MenuItem}, {Location}
_CONCEPT_RE = re.compile(r"\{([A-Z][a-zA-Z]+)\}")


def _parse_relationship_label(fstring_value: str) -> tuple[list[str], list[PropertyDef], str]:
    """
    Parse a relationship f-string like:
      "{MenuItem} has {Float:Retail Price} has {Integer:Prep Time (Seconds)}"
      "{OrderItem} belongs to {Order}"
      "{SupplyTransfer} moves {InventoryItem} via {Location}"

    Returns:
      - target_concepts: list of concept names referenced (excluding the first/source)
      - scalar_properties: list of PropertyDef for scalar fields
      - label: cleaned natural-language label
    """
    scalars: list[PropertyDef] = []
    target_concepts: list[str] = []

    # Collect scalars first (before stripping them for the label)
    for m in _SCALAR_RE.finditer(fstring_value):
        scalars.append(PropertyDef(
            name=_to_snake(m.group(2)),
            type=m.group(1),
            relationship_group="",   # filled in by caller
        ))

    # Strip scalar tokens to find concept tokens
    stripped = _SCALAR_RE.sub("", fstring_value)
    concept_tokens = _CONCEPT_RE.findall(stripped)
    # First token is always the source concept; rest are targets
    if len(concept_tokens) > 1:
        target_concepts = concept_tokens[1:]

    # Build a clean label
    label = re.sub(r"\{[^}]+\}", lambda m: _clean_token(m.group()), fstring_value).strip()
    label = re.sub(r"\s+", " ", label)

    return target_concepts, scalars, label


def _clean_token(token: str) -> str:
    """Turn {String:Item Name} → 'Item Name', {MenuItem} → 'MenuItem'."""
    inner = token.strip("{}")
    if ":" in inner:
        return inner.split(":", 1)[1].strip()
    return inner


def _to_snake(name: str) -> str:
    """'Retail Price' → 'retail_price', 'Avg Wait Time (Seconds)' → 'avg_wait_time_seconds'"""
    s = re.sub(r"[^a-zA-Z0-9\s]", "", name)
    return re.sub(r"\s+", "_", s.strip()).lower()


def _ast_str_value(node: ast.expr) -> Optional[str]:
    """
    Safely extract a string constant from an AST node.

    Handles plain strings and f-strings.  In PyREL model files the f-string
    tokens take two forms:

      {Order}                 → FormattedValue(value=Name('Order'), format_spec=None)
      {Float:Total Amount}    → FormattedValue(value=Name('Float'),
                                    format_spec=JoinedStr([Constant('Total Amount')]))

    Python parses ``{Float:Total Amount}`` as "format the expression `Float`
    using the format spec `Total Amount`" — NOT as a subscript.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant):
                parts.append(str(v.value))
            elif isinstance(v, ast.FormattedValue):
                if not isinstance(v.value, ast.Name):
                    continue
                type_name = v.value.id
                if v.format_spec and isinstance(v.format_spec, ast.JoinedStr):
                    # {Float:Total Amount}  — typed scalar property
                    spec_parts = [
                        str(p.value)
                        for p in v.format_spec.values
                        if isinstance(p, ast.Constant)
                    ]
                    prop_label = "".join(spec_parts)
                    parts.append(f"{{{type_name}:{prop_label}}}")
                else:
                    # {Order}  — bare concept reference
                    parts.append(f"{{{type_name}}}")
        return "".join(parts)
    return None


def _get_kwarg(call: ast.Call, key: str) -> Optional[ast.expr]:
    for kw in call.keywords:
        if kw.arg == key:
            return kw.value
    return None


# ── Main parser ───────────────────────────────────────────────────────────────

class ModelParser:
    def __init__(self, source: str):
        self._source = source
        self._tree = ast.parse(_sanitize_source(source))
        self._model_name: str = ""
        self._source_tables: dict[str, str] = {}
        self._concepts: dict[str, ConceptDef] = {}
        self._relationships: list[RelationshipDef] = []

    # -- Public ----------------------------------------------------------------

    def parse(self) -> ParsedModel:
        self._extract_model_name()
        self._extract_source_tables()
        self._extract_concepts()
        self._extract_relationships()
        self._extract_column_mappings()
        self._extract_computed_properties()
        return ParsedModel(
            model_name=self._model_name,
            source_tables=self._source_tables,
            concepts=list(self._concepts.values()),
            relationships=self._relationships,
        )

    @classmethod
    def from_file(cls, path: str | Path) -> "ModelParser":
        return cls(Path(path).read_text())

    # -- Private ---------------------------------------------------------------

    def _extract_model_name(self):
        """Find: model = Model("coffee_shop_vp_ops")"""
        for node in ast.walk(self._tree):
            if (
                isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "Model"
                and node.value.args
            ):
                v = node.value.args[0]
                if isinstance(v, ast.Constant):
                    self._model_name = v.value
                    return

    def _extract_source_tables(self):
        """
        Find all model.Table("DB.SCHEMA.TABLE") calls and record the attribute
        name they're assigned to under the Sources class hierarchy.
        """
        for node in ast.walk(self._tree):
            if not isinstance(node, ast.ClassDef):
                continue
            # Walk into nested class bodies looking for assignments
            for stmt in ast.walk(node):
                if not isinstance(stmt, ast.Assign):
                    continue
                if not (
                    isinstance(stmt.value, ast.Call)
                    and isinstance(stmt.value.func, ast.Attribute)
                    and stmt.value.func.attr == "Table"
                ):
                    continue
                if stmt.value.args:
                    table_path = stmt.value.args[0]
                    if isinstance(table_path, ast.Constant):
                        # target name is the attribute short name (e.g. "baristas")
                        for target in stmt.targets:
                            if isinstance(target, ast.Name):
                                self._source_tables[target.id] = table_path.value

    def _extract_concepts(self):
        """
        Find: Foo = model.Concept("Foo", identify_by={...})
        and: model.define(Foo.new(...))
        """
        # Pass 1: collect concept definitions
        for node in ast.walk(self._tree):
            if not isinstance(node, ast.Assign):
                continue
            val = node.value
            if not (
                isinstance(val, ast.Call)
                and isinstance(val.func, ast.Attribute)
                and val.func.attr == "Concept"
                and val.args
            ):
                continue
            name_node = val.args[0]
            if not isinstance(name_node, ast.Constant):
                continue
            concept_name = name_node.value

            identify_by = self._parse_identify_by(val)
            source_table = self._infer_source_table(val)

            self._concepts[concept_name] = ConceptDef(
                name=concept_name,
                identify_by=identify_by,
                source_table=source_table,
            )

    def _parse_identify_by(self, concept_call: ast.Call) -> list[dict]:
        """Parse identify_by={"Location ID": Integer, ...}"""
        kwarg = _get_kwarg(concept_call, "identify_by")
        if not kwarg or not isinstance(kwarg, ast.Dict):
            return []
        result = []
        for k, v in zip(kwarg.keys, kwarg.values):
            if isinstance(k, ast.Constant) and isinstance(v, ast.Name):
                result.append({"name": k.value, "type": v.id})
        return result

    def _infer_source_table(self, concept_call: ast.Call) -> Optional[str]:
        """
        Try to infer source table from the immediately following model.define(Concept.new(...)) call.
        We look for model.define calls where the inner call's func is Attribute with attr="new"
        on the same concept name.
        This is a best-effort; full table resolution is also available via _source_tables.
        """
        # Will be resolved post-hoc in _extract_relationships where we see the full
        # filter_by / Table chain. Return None for now; filled below.
        return None

    def _extract_relationships(self):
        """
        Find:
          Foo.bar = model.Relationship(f"...", short_name="foo_bar")
        and resolve source_table from the define() calls.
        """
        for node in ast.walk(self._tree):
            if not isinstance(node, ast.Assign):
                continue
            val = node.value
            if not (
                isinstance(val, ast.Call)
                and isinstance(val.func, ast.Attribute)
                and val.func.attr == "Relationship"
            ):
                continue

            # target: Foo.bar
            for target in node.targets:
                if not isinstance(target, ast.Attribute):
                    continue
                concept_name = target.value.id if isinstance(target.value, ast.Name) else None
                rel_attr_name = target.attr
                if not concept_name or concept_name not in self._concepts:
                    continue

                # Parse the f-string label (first positional arg)
                label_raw = ""
                if val.args:
                    label_raw = _ast_str_value(val.args[0]) or ""

                short_name_node = _get_kwarg(val, "short_name")
                short_name = ""
                if short_name_node and isinstance(short_name_node, ast.Constant):
                    short_name = short_name_node.value

                target_concepts, scalars, label = _parse_relationship_label(label_raw)

                # Tag scalars with this relationship group
                for s in scalars:
                    s.relationship_group = short_name

                rel = RelationshipDef(
                    name=rel_attr_name,
                    short_name=short_name,
                    label=label,
                    source_concept=concept_name,
                    target_concepts=target_concepts,
                    scalar_properties=scalars,
                )
                self._relationships.append(rel)

                # Attach to concept
                concept = self._concepts[concept_name]
                concept.relationships.append(rel)
                concept.properties.extend(scalars)

        # Resolve source tables from model.define() calls
        self._resolve_source_tables()

    def _resolve_source_tables(self):
        """
        Walk model.define(...) calls.
        For each Concept.filter_by(...) chain, extract the table attribute name
        and look it up in self._source_tables.

        Pattern:
          model.define(
              Foo.filter_by(Foo ID=Sources.db.schema.foo.Foo_ID)
                 .rel_name(...)
          )
        We just look for any Attribute node whose value chain ends in something
        we recognise as a table name.
        """
        for node in ast.walk(self._tree):
            if not (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
                and node.value.func.attr == "define"
            ):
                continue

            for inner in ast.walk(node):
                if not isinstance(inner, ast.Call):
                    continue
                func = inner.func
                if not (isinstance(func, ast.Attribute) and func.attr == "new"):
                    continue
                # func.value is the concept Name or filter_by call
                concept_name = self._resolve_concept_from_chain(func.value)
                if concept_name and concept_name in self._concepts:
                    table = self._find_table_in_args(inner)
                    if table and self._concepts[concept_name].source_table is None:
                        self._concepts[concept_name].source_table = table

    def _resolve_concept_from_chain(self, node: ast.expr) -> Optional[str]:
        """Walk back through .filter_by().new() to find the base concept Name."""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            return self._resolve_concept_from_chain(node.func.value)
        return None

    def _find_table_in_args(self, call: ast.Call) -> Optional[str]:
        """Look for Sources.x.y.z.table_attr references in call args/kwargs."""
        for arg in call.args:
            result = self._attr_chain_to_table(arg)
            if result:
                return result
        for kw in call.keywords:
            result = self._attr_chain_to_table(kw.value)
            if result:
                return result
        return None

    def _attr_chain_to_table(self, node: ast.expr) -> Optional[str]:
        """
        Given an attribute chain like Sources.bespoke.coffee_shop.baristas.barista_id,
        find the segment that matches a known table name.
        """
        if not isinstance(node, ast.Attribute):
            return None
        parts = []
        cur = node
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        parts.reverse()
        # Walk segments: if any segment is a key in _source_tables, return it
        for part in parts:
            if part in self._source_tables:
                return self._source_tables[part]
        return None

    def _extract_column_mappings(self):
        """
        Walk model.define() calls to extract physical Snowflake column names.

        Two patterns:

        1. Concept PK from `.new()`:
              model.define(Barista.new(barista_id=Sources...baristas.barista_id))
           → concept.pk_col = "barista_id"  (last attr in the Sources chain)

        2. Relationship FK from `.filter_by().rel_name(TargetConcept.filter_by(...))`:
              model.define(
                  Barista.filter_by(Barista_ID=Sources...baristas.Barista_ID)
                         .home_location(Location.filter_by(Location_ID=Sources...baristas.Location_ID), ...)
              )
           → For relationship "home_location" on Barista:
                 source_pk_col  = "barista_id"  (last attr of source filter_by kwarg value)
                 fk_cols["Location"] = "location_id"  (last attr of target filter_by kwarg value)
        """
        # Build a reverse map: short_name -> RelationshipDef for quick lookup
        rel_by_short: dict[str, RelationshipDef] = {}
        for r in self._relationships:
            rel_by_short[r.short_name] = r
        rel_by_attr: dict[tuple[str, str], RelationshipDef] = {}
        for r in self._relationships:
            rel_by_attr[(r.source_concept, r.name)] = r

        for node in ast.walk(self._tree):
            if not (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
                and node.value.func.attr == "define"
            ):
                continue

            define_arg = node.value.args[0] if node.value.args else None
            if define_arg is None:
                continue

            # ── Pattern 1: Concept.new(col=Sources...table.col) ──────────────
            if (
                isinstance(define_arg, ast.Call)
                and isinstance(define_arg.func, ast.Attribute)
                and define_arg.func.attr == "new"
            ):
                concept_name = self._resolve_concept_from_chain(define_arg.func.value)
                if concept_name and concept_name in self._concepts:
                    # First keyword arg value → last attribute = physical PK column
                    if define_arg.keywords:
                        pk_col = self._last_attr(define_arg.keywords[0].value)
                        if pk_col:
                            self._concepts[concept_name].pk_col = pk_col.lower()

            # ── Pattern 2: Concept.filter_by(...).rel_name(...) ──────────────
            elif (
                isinstance(define_arg, ast.Call)
                and isinstance(define_arg.func, ast.Attribute)
            ):
                rel_name = define_arg.func.attr
                chain_root = define_arg.func.value  # Concept.filter_by(...)

                if not (
                    isinstance(chain_root, ast.Call)
                    and isinstance(chain_root.func, ast.Attribute)
                    and chain_root.func.attr == "filter_by"
                ):
                    continue

                concept_name = self._resolve_concept_from_chain(chain_root.func.value)
                if not concept_name or concept_name not in self._concepts:
                    continue

                rel = rel_by_attr.get((concept_name, rel_name))
                if rel is None:
                    continue

                # Source PK col: first kwarg value of the outer filter_by
                if chain_root.keywords:
                    src_pk = self._last_attr(chain_root.keywords[0].value)
                    if src_pk:
                        rel.source_pk_col = src_pk.lower()
                    # Also extract which Snowflake table the source filter_by references
                    src_table = self._attr_chain_to_table(chain_root.keywords[0].value)
                    if src_table:
                        rel.source_filter_table = src_table

                # FK cols: positional args that are TargetConcept.filter_by(...)
                for arg in define_arg.args:
                    if not (
                        isinstance(arg, ast.Call)
                        and isinstance(arg.func, ast.Attribute)
                        and arg.func.attr == "filter_by"
                    ):
                        continue
                    target_name = self._resolve_concept_from_chain(arg.func.value)
                    if not target_name or target_name not in self._concepts:
                        continue
                    if arg.keywords:
                        fk_col = self._last_attr(arg.keywords[0].value)
                        if fk_col:
                            rel.fk_cols[target_name] = fk_col.lower()

    def _last_attr(self, node: ast.expr) -> Optional[str]:
        """Return the rightmost attribute name in a chain like Sources.a.b.c → 'c'."""
        if isinstance(node, ast.Attribute):
            return node.attr
        return None

    def _extract_computed_properties(self):
        """
        Find @define(concepts.Foo) class blocks and extract @property methods.
        """
        for node in ast.walk(self._tree):
            if not isinstance(node, ast.ClassDef):
                continue

            # Look for decorators: @define(concepts.Foo)
            concept_name = self._concept_from_define_decorator(node)
            if not concept_name or concept_name not in self._concepts:
                continue

            concept = self._concepts[concept_name]
            for item in node.body:
                if not isinstance(item, ast.FunctionDef):
                    continue
                # Must have @property decorator
                has_property = any(
                    (isinstance(d, ast.Name) and d.id == "property")
                    for d in item.decorator_list
                )
                if not has_property:
                    continue

                return_type = None
                if item.returns:
                    return_type = ast.unparse(item.returns)

                docstring = None
                if (
                    item.body
                    and isinstance(item.body[0], ast.Expr)
                    and isinstance(item.body[0].value, ast.Constant)
                ):
                    docstring = item.body[0].value.value

                concept.computed_properties.append(ComputedPropertyDef(
                    name=item.name,
                    return_type=return_type,
                    docstring=docstring,
                ))

    def _concept_from_define_decorator(self, class_node: ast.ClassDef) -> Optional[str]:
        """
        From @define(concepts.Foo) or @define(Foo), extract "Foo".
        """
        for dec in class_node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            if not (isinstance(dec.func, ast.Name) and dec.func.id == "define"):
                continue
            if not dec.args:
                continue
            arg = dec.args[0]
            # concepts.Foo
            if isinstance(arg, ast.Attribute):
                return arg.attr
            # Foo
            if isinstance(arg, ast.Name):
                return arg.id
        return None
