"""
LDVELH - Knowledge Graph Module
Gestion du graphe de connaissances
"""

# Base populator
from kg.populator import (
    KnowledgeGraphPopulator,
    EntityRegistry,
)

# Specialized populators
from kg.specialized_populator import (
    WorldPopulator,
    ExtractionPopulator,
)

# Context builder
from kg.context_builder import ContextBuilder

__all__ = [
    # Registry
    "EntityRegistry",
    # Populators
    "KnowledgeGraphPopulator",
    "WorldPopulator",
    "ExtractionPopulator",
    # Context
    "ContextBuilder",
]
