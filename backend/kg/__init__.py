"""
LDVELH - Knowledge Graph Module
Gestion du graphe de connaissances

Architecture:
- reader.py: Lecture seule (SELECT)
- populator.py: Écriture (INSERT/UPDATE/DELETE)
- specialized_populator.py: WorldPopulator, ExtractionPopulator
- context_builder.py: Construction contexte narrateur

No re-export: importing a submodule (kg.item_writes, which services.identity uses) must
not load the populators, which import services.identity.service (#168).
"""
