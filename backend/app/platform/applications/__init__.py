"""Application layer: what FIHRIST sells, as opposed to what it runs.

A *module* is a code boundary; an *application* is a commercial product that may
use several modules. ``retail.purchasing`` is an application; ``purchasing/`` is
a module it uses. Keeping the two apart is what lets one shop buy purchasing
without buying a warehouse.
"""

from app.platform.applications import install as _install  # noqa: F401  (registers the setup hook)
