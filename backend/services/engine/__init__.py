"""
LDVELH - Engine Service
Strategy pattern: get_engine(engine_type) returns the correct engine implementation.
"""

from schema.engine import EngineType

from .base import BaseEngine
from .none import NoneEngine
from .narrative import NarrativeEngine
from .fate_core import FateCoreEngine
from .d6 import D6Engine

_ENGINE_MAP: dict[EngineType, type[BaseEngine]] = {
    EngineType.NONE: NoneEngine,
    EngineType.NARRATIVE: NarrativeEngine,
    EngineType.FATE_CORE: FateCoreEngine,
    EngineType.D6: D6Engine,
}

# Singleton instances (engines are stateless)
_instances: dict[EngineType, BaseEngine] = {}


def get_engine(engine_type: str | EngineType) -> BaseEngine:
    """Get the engine implementation for the given type."""
    if isinstance(engine_type, str):
        engine_type = EngineType(engine_type)

    if engine_type not in _instances:
        _instances[engine_type] = _ENGINE_MAP[engine_type]()

    return _instances[engine_type]


__all__ = ["BaseEngine", "get_engine", "EngineType"]
