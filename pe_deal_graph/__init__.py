"""Northwind deal graph: a synthetic PE deal-sourcing and scoring knowledge graph (RelationalAI rules + graph).

Package layout (one-way dependencies: core -> rules / graphs -> queries -> export):

    pe_deal_graph.model.core    concepts, Snowflake bindings, and the declared derived layer (R08)
    pe_deal_graph.model.rules   derived properties: fit, readiness, score, tiers, Knows, conflicts (R09)
    pe_deal_graph.model.graphs  graph constructions and algorithm outputs (R10)
    pe_deal_graph.queries       one zero-argument function per hero question (R11)

Import the model with ``from pe_deal_graph.model import model`` (or ``get_model()``).
This top-level package deliberately does not re-export ``model``: the attribute name
``pe_deal_graph.model`` must stay bound to the subpackage, not to the Model object.
"""

__version__ = "0.1.0"
AS_OF_ISO = "2026-10-01"  # CONFIG AS_OF_DATE; the PyRel date constant is pe_deal_graph.model.core.AS_OF
