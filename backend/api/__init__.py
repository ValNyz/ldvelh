"""
LDVELH - API Module
Routes et utilitaires FastAPI

NOTE: Les routers NE sont PAS importés ici pour éviter les imports circulaires.
      Importer directement depuis api.routes et api.tooltips si nécessaire.
"""

from api.dependencies import get_pool, get_connection, get_settings_dep
from api.streaming import SSEWriter, SSEEvent, create_sse_response, build_display_text

__all__ = [
    # Dependencies
    "get_pool",
    "get_connection",
    "get_settings_dep",
    # Streaming
    "SSEWriter",
    "SSEEvent",
    "create_sse_response",
    "build_display_text",
    # Routers - importer directement depuis api.routes / api.tooltips
    # "main_router",      # from api.routes import router
    # "tooltips_router",  # from api.tooltips import router
]
