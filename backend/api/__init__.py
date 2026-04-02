"""
LDVELH - API Module
Routes et utilitaires FastAPI

NOTE: Les routers NE sont PAS importés ici pour éviter les imports circulaires.
      Importer directement depuis api.routes et api.tooltips si nécessaire.
"""

from api.dependencies import get_pool, get_connection, get_settings_dep
from api.streaming import SSEWriter, SSEEvent, create_sse_response, build_display_text

__all__ = [
    "get_pool",
    "get_connection",
    "get_settings_dep",
    "SSEWriter",
    "SSEEvent",
    "create_sse_response",
    "build_display_text",
]
