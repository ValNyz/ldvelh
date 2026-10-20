"""
LDVELH - Knowledge Graph Module
Gestion du graphe de connaissances

Architecture:
- reader.py: Lecture seule (SELECT)
- populator.py: Écriture (INSERT/UPDATE/DELETE)
- specialized_populator.py: WorldPopulator, ExtractionPopulator
- context_builder.py: Construction contexte narrateur
"""

from kg.populator import KnowledgeGraphPopulator
from kg.reader import KnowledgeGraphReader
from kg.specialized_populator import ExtractionPopulator, WorldPopulator

__all__ = [
    "ExtractionPopulator",
    "KnowledgeGraphPopulator",
    "KnowledgeGraphReader",
    "WorldPopulator",
]
