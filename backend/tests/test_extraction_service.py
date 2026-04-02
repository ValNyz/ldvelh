"""
Tests unitaires pour extraction_service.py (batch extraction)
Focus sur les helpers et la logique pure (pas d'I/O)
"""

import json
import pytest
from prompts.extractor_prompts import (
    BATCH_EXTRACTION_SYSTEM,
    build_batch_extraction_prompt,
)


class TestBatchExtractionPrompt:
    """Tests pour build_batch_extraction_prompt"""

    def test_basic_prompt(self):
        """Prompt basique avec un seul texte"""
        prompt = build_batch_extraction_prompt(
            narrative_texts=["Valentin entre dans le bar."],
            cycle=3,
            known_entities=["Ossek", "Le Quart de Cycle"],
        )

        assert "Cycle: 3" in prompt
        assert "Ossek" in prompt
        assert "Le Quart de Cycle" in prompt
        assert "Valentin entre dans le bar." in prompt

    def test_multiple_texts_joined(self):
        """Plusieurs textes joints par séparateur"""
        prompt = build_batch_extraction_prompt(
            narrative_texts=["Texte 1.", "Texte 2.", "Texte 3."],
            cycle=5,
            known_entities=[],
        )

        assert "Texte 1." in prompt
        assert "Texte 2." in prompt
        assert "Texte 3." in prompt
        assert "---" in prompt

    def test_empty_entities(self):
        """Aucune entité connue"""
        prompt = build_batch_extraction_prompt(
            narrative_texts=["Test."],
            cycle=1,
            known_entities=[],
        )
        assert "Aucune" in prompt

    def test_inventory_hints_included(self):
        """Inventory hints inclus dans le prompt"""
        hints = [
            {"item_name": "Carte d'accès", "action": "acquire"},
            {"item_name": "Crédits", "action": "lose"},
        ]
        prompt = build_batch_extraction_prompt(
            narrative_texts=["Test."],
            cycle=2,
            known_entities=[],
            inventory_hints=hints,
        )

        assert "Carte d'accès" in prompt
        assert "acquire" in prompt

    def test_no_inventory_hints(self):
        """Pas d'inventory hints"""
        prompt = build_batch_extraction_prompt(
            narrative_texts=["Test."],
            cycle=2,
            known_entities=[],
            inventory_hints=None,
        )
        assert "inventory_hints" not in prompt


class TestBatchExtractionSystem:
    """Tests pour le system prompt batch"""

    def test_contains_strict_keys(self):
        """Le prompt contient les contraintes strictes"""
        assert "CONTRAINTE STRICTE" in BATCH_EXTRACTION_SYSTEM

    def test_contains_all_root_keys(self):
        """Le prompt documente toutes les clés racine"""
        root_keys = [
            "segment_summary",
            "entities_created",
            "entities_updated",
            "objects_created",
            "facts",
            "relations_created",
            "relations_updated",
            "arcs_created",
            "arcs_resolved",
            "events_scheduled",
        ]
        for key in root_keys:
            assert key in BATCH_EXTRACTION_SYSTEM, f"Missing root key: {key}"

    def test_no_protagonist_state_extraction(self):
        """Le batch ne doit PAS extraire les jauges/crédits (gérés live)"""
        assert "jauges" in BATCH_EXTRACTION_SYSTEM.lower() or "gérés par le narrateur" in BATCH_EXTRACTION_SYSTEM
        assert "NE PAS les extraire" in BATCH_EXTRACTION_SYSTEM or "NE PAS" in BATCH_EXTRACTION_SYSTEM
