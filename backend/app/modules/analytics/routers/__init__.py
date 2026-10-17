"""analytics/routers — sub-package entry point.

Imports the sub-routers so their ``@router.*`` decorators execute and register
their endpoints on the shared ``router`` from ``_deps.py``.
"""

from app.modules.analytics.routers import metrics as _metrics  # noqa: F401
from app.modules.analytics.routers import overview as _overview  # noqa: F401
from app.modules.analytics.routers import retention as _retention  # noqa: F401
from app.modules.analytics.routers._deps import router  # noqa: F401
