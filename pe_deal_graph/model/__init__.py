"""Model package. ``from pe_deal_graph.model import model`` gives the shared Model with core loaded.

rules.py (R09) and graphs.py (R10) are imported explicitly by their consumers
(``import pe_deal_graph.model.rules``), so importing this package never runs reasoning code.
"""

from .core import *  # noqa: F401,F403
from .core import __all__  # noqa: F401
