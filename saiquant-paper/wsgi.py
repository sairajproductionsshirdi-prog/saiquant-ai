"""WSGI entry point for cloud deployment (Render/railway/etc.)."""
from saiquant.dashboard import app
from saiquant import charts   # noqa: F401 — registers chart routes
from saiquant import actions  # noqa: F401 — registers web-command routes
