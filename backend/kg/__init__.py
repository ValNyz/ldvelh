"""
LDVELH - Knowledge Graph Module
Gestion du graphe de connaissances

Architecture:
- reader.py: Lecture seule (SELECT)
- populator.py: Écriture (INSERT/UPDATE/DELETE)
- specialized_populator.py: WorldPopulator, ExtractionPopulator
- context_builder.py: Construction contexte narrateur
"""

# Reader (SELECT)
from kg.reader import (
    KnowledgeGraphReader,
)

# Base populator (INSERT/UPDATE/DELETE)
from kg.populator import (
    KnowledgeGraphPopulator,
    EntityRegistry,
)

# Specialized populators
from kg.specialized_populator import (
    WorldPopulator,
    ExtractionPopulator,
)

__all__ = [
    # Reader
    "KnowledgeGraphReader",
    # Registry
    "EntityRegistry",
    # Populators
    "KnowledgeGraphPopulator",
    "WorldPopulator",
    "ExtractionPopulator",
    # Context
    "ContextBuilder",
]
