"""
Tests des fonctions utilitaires dans les prompts.
Pas de LLM, juste logique pure.
"""

from prompts.extractor_prompts import (
    should_run_extraction,
    extract_object_hints,
    BATCH_EXTRACTION_SYSTEM,
    build_batch_extraction_prompt,
)
from schema import NarrationHints


# =============================================================================
# TESTS should_run_extraction
# =============================================================================


class TestShouldRunExtraction:
    """Teste la logique de décision d'extraction"""

    def test_empty_hints_no_extraction(self):
        """Aucun hint → pas d'extraction"""
        hints = NarrationHints()
        assert should_run_extraction(hints) is False

    def test_new_entities_triggers_extraction(self):
        """Nouvelles entités → extraction"""
        hints = NarrationHints(new_entities_mentioned=["Alice"])
        assert should_run_extraction(hints) is True

    def test_relationship_changed_triggers_extraction(self):
        """Relation modifiée → extraction"""
        hints = NarrationHints(relationships_changed=True)
        assert should_run_extraction(hints) is True

    def test_protagonist_state_triggers_extraction(self):
        """État protagoniste modifié → extraction"""
        hints = NarrationHints(protagonist_state_changed=True)
        assert should_run_extraction(hints) is True

    def test_information_learned_triggers_extraction(self):
        """Information apprise → extraction"""
        hints = NarrationHints(information_learned=True)
        assert should_run_extraction(hints) is True

    def test_arc_advanced_triggers_extraction(self):
        """Arc avancé → extraction"""
        hints = NarrationHints(arc_advanced=["Arc de Marie"])
        assert should_run_extraction(hints) is True

    def test_arc_resolved_triggers_extraction(self):
        """Arc résolu → extraction"""
        hints = NarrationHints(arc_resolved=["Promesse tenue"])
        assert should_run_extraction(hints) is True

    def test_new_arc_triggers_extraction(self):
        """Nouvel engagement → extraction"""
        hints = NarrationHints(new_arc_created=True)
        assert should_run_extraction(hints) is True

    def test_event_scheduled_triggers_extraction(self):
        """Événement planifié → extraction"""
        hints = NarrationHints(event_scheduled=True)
        assert should_run_extraction(hints) is True

    def test_event_occurred_triggers_extraction(self):
        """Événement survenu → extraction"""
        hints = NarrationHints(event_occurred=True)
        assert should_run_extraction(hints) is True

    def test_multiple_hints_triggers_extraction(self):
        """Plusieurs hints → extraction"""
        hints = NarrationHints(
            new_entities_mentioned=["Bob"],
            relationships_changed=True,
            protagonist_state_changed=True,
        )
        assert should_run_extraction(hints) is True


# =============================================================================
# TESTS extract_object_hints
# =============================================================================


class TestExtractObjectHints:
    """Teste l'extraction des hints d'objets"""

    def test_empty_list(self):
        """Liste vide → pas de hints"""
        assert extract_object_hints([]) == []

    def test_only_acquire_with_hint(self):
        """Seuls les acquire avec object_hint comptent"""
        changes = [
            {"action": "acquire", "object_hint": "Clé magnétique"},
            {"action": "lose", "object_ref": "Crédits"},
            {"action": "use", "object_ref": "Lampe"},
        ]
        hints = extract_object_hints(changes)
        assert hints == ["Clé magnétique"]

    def test_acquire_without_hint_ignored(self):
        """acquire avec object_ref (pas hint) ignoré"""
        changes = [
            {"action": "acquire", "object_ref": "Objet existant"},
        ]
        hints = extract_object_hints(changes)
        assert hints == []

    def test_multiple_hints(self):
        """Plusieurs hints extraits"""
        changes = [
            {"action": "acquire", "object_hint": "Premier objet"},
            {"action": "acquire", "object_hint": "Deuxième objet"},
            {"action": "acquire", "object_ref": "Existant"},
        ]
        hints = extract_object_hints(changes)
        assert hints == ["Premier objet", "Deuxième objet"]


# =============================================================================
# TESTS NarrationHints.needs_extraction PROPERTY
# =============================================================================


class TestNarrationHintsProperty:
    """Teste la propriété needs_extraction de NarrationHints"""

    def test_needs_extraction_default_false(self):
        """Par défaut, needs_extraction est False"""
        hints = NarrationHints()
        assert hints.needs_extraction is False

    def test_needs_extraction_with_list(self):
        """Liste non vide → True"""
        hints = NarrationHints(new_entities_mentioned=["Test"])
        assert hints.needs_extraction is True

    def test_needs_extraction_with_bool(self):
        """Bool True → True"""
        hints = NarrationHints(relationships_changed=True)
        assert hints.needs_extraction is True

    def test_needs_extraction_combined(self):
        """Combine plusieurs conditions"""
        # Tout à False/vide
        hints = NarrationHints(
            new_entities_mentioned=[],
            relationships_changed=False,
            protagonist_state_changed=False,
        )
        assert hints.needs_extraction is False

        # Un seul à True suffit
        hints.protagonist_state_changed = True
        assert hints.needs_extraction is True


# =============================================================================
# TESTS NARRATOR PROMPT BUILDER
# =============================================================================


class TestNarratorPromptBuilder:
    """Teste build_narrator_context_prompt"""

    def _make_base_context(self, **overrides):
        """Helper pour créer un NarrationContext de base"""
        from schema import (
            NarrationContext,
            LocationSummary,
            ProtagonistState,
            GaugeState,
        )

        defaults = dict(
            current_cycle=1,
            current_date="Lundi 1er Janvier 2847",
            current_time="10h00",
            current_location=LocationSummary(
                name="Le Quart de Cycle",
                type="cafe",
                sector="Quai Central",
                atmosphere="calme",
            ),
            protagonist=ProtagonistState(
                name="Valentin",
                credits=1500,
                energy=GaugeState(value=3.0),
                morale=GaugeState(value=3.0),
                health=GaugeState(value=4.0),
                hobbies=["lecture"],
            ),
            organizations=[],
            all_npcs=[],
            player_input="Je regarde autour de moi",
            world_name="Escale Méridienne",
            world_atmosphere="industrielle",
        )
        defaults.update(overrides)
        return NarrationContext(**defaults)

    def test_build_narrator_context_prompt_basic(self):
        """Le builder génère un prompt valide"""
        from prompts.narrator_prompt import build_narrator_context_prompt

        context = self._make_base_context()
        prompt = build_narrator_context_prompt(context)

        # Vérifie que les sections clés sont présentes
        assert "CONTEXTE ACTUEL" in prompt
        assert "TEMPS" in prompt
        assert "LIEU ACTUEL" in prompt
        assert "PROTAGONISTE" in prompt
        assert "ACTION DU JOUEUR" in prompt
        assert "Je regarde autour de moi" in prompt
        assert "Valentin" in prompt
        assert "Le Quart de Cycle" in prompt

    def test_requested_entity_details_rendered(self):
        """Les détails demandés sont rendus dans le prompt"""
        from prompts.narrator_prompt import build_narrator_context_prompt

        context = self._make_base_context(
            requested_entity_details={
                "Kess": {
                    "_entity_type": "character",
                    "description": "Mécanicienne talentueuse",
                    "occupation": "Ingénieure",
                    "species": "human",
                    "traits": ["pragmatique", "directe"],
                    "relation_level": 4,
                    "recent_facts": [
                        "A réparé le générateur du secteur Est",
                    ],
                },
                "Terminal 7": {
                    "_entity_type": "location",
                    "sector": "Quai Nord",
                    "atmosphere": "bruyant et animé",
                    "location_type": "bar",
                },
            }
        )

        prompt = build_narrator_context_prompt(context)

        assert "DÉTAILS DEMANDÉS" in prompt
        assert "Kess" in prompt
        assert "Mécanicienne talentueuse" in prompt
        assert "pragmatique" in prompt
        assert "niveau 4/10" in prompt
        assert "A réparé le générateur" in prompt
        assert "Terminal 7" in prompt
        assert "Quai Nord" in prompt

    def test_no_details_section_when_empty(self):
        """Pas de section DÉTAILS DEMANDÉS si aucun détail demandé"""
        from prompts.narrator_prompt import build_narrator_context_prompt

        context = self._make_base_context()
        prompt = build_narrator_context_prompt(context)

        assert "DÉTAILS DEMANDÉS" not in prompt


# =============================================================================
# TESTS WORLD GENERATION PROMPT BUILDER
# =============================================================================


class TestWorldGenerationPromptBuilder:
    """Teste les fonctions du world_generation_prompt"""

    def test_build_world_generation_user_prompt_default(self):
        """Le builder génère un prompt avec les sections par défaut"""
        from prompts.world_generation_prompt import build_world_generation_user_prompt

        prompt = build_world_generation_user_prompt()

        assert "PERSONNAGE PRINCIPAL" in prompt
        assert "Valentin" in prompt
        assert "EMPLOI" in prompt
        assert "CHECKLIST FINALE" in prompt

    def test_build_world_generation_user_prompt_unemployed(self):
        """Le builder gère le mode sans emploi"""
        from prompts.world_generation_prompt import build_world_generation_user_prompt

        prompt = build_world_generation_user_prompt(employer_preference="unemployed")

        assert "SANS emploi" in prompt

    def test_build_world_generation_user_prompt_with_mandatory_npcs(self):
        """Le builder inclut les PNJs obligatoires"""
        from prompts.world_generation_prompt import build_world_generation_user_prompt

        mandatory = [
            {"name": "Alice", "age": 25, "gender": "femme", "romantic_potential": True}
        ]
        prompt = build_world_generation_user_prompt(mandatory_npcs=mandatory)

        assert "PNJ OBLIGATOIRES" in prompt
        assert "Alice" in prompt

    def test_get_full_generation_prompt_structure(self):
        """get_full_generation_prompt retourne la bonne structure"""
        from prompts.world_generation_prompt import get_full_generation_prompt

        result = get_full_generation_prompt()

        assert "system" in result
        assert "user" in result
        assert len(result["system"]) > 100
        assert len(result["user"]) > 100


# =============================================================================
# TESTS BATCH EXTRACTION PROMPT
# =============================================================================


class TestBatchExtractionPrompt:
    """Teste le prompt d'extraction batch"""

    def test_batch_system_has_strict_keys(self):
        """BATCH_EXTRACTION_SYSTEM contient la contrainte de clés strictes"""
        assert "EXACTEMENT les clés JSON" in BATCH_EXTRACTION_SYSTEM

    def test_batch_system_documents_all_root_keys(self):
        """BATCH_EXTRACTION_SYSTEM documente toutes les clés racine"""
        for key in [
            "segment_summary", "entities_created", "entities_updated",
            "objects_created", "facts", "relations_created",
            "relations_updated", "arcs_created", "arcs_updated",
            "arcs_resolved", "events_scheduled",
        ]:
            assert key in BATCH_EXTRACTION_SYSTEM, f"Root key missing: {key}"

    def test_batch_system_documents_entity_keys(self):
        """BATCH_EXTRACTION_SYSTEM documente les clés d'entité"""
        for key in ["entity_type", "name", "known_by_protagonist", "data",
                     "entity_ref", "now_known", "real_name", "changes"]:
            assert key in BATCH_EXTRACTION_SYSTEM, f"Entity key missing: {key}"

    def test_batch_system_documents_fact_keys(self):
        """BATCH_EXTRACTION_SYSTEM documente les clés de faits"""
        for key in ["fact_type", "description", "semantic_key", "importance", "participants"]:
            assert key in BATCH_EXTRACTION_SYSTEM, f"Fact key missing: {key}"

    def test_batch_system_documents_relation_types(self):
        """BATCH_EXTRACTION_SYSTEM documente les types de relation"""
        for rtype in ["knows", "friend_of", "enemy_of", "romantic",
                      "employed_by", "colleague_of", "frequents"]:
            assert rtype in BATCH_EXTRACTION_SYSTEM, f"Relation type missing: {rtype}"

    def test_batch_system_documents_arc_domains(self):
        """BATCH_EXTRACTION_SYSTEM documente les domaines d'arc"""
        for domain in ["professional", "romantic", "health", "social", "mystery"]:
            assert domain in BATCH_EXTRACTION_SYSTEM, f"Arc domain missing: {domain}"

    def test_batch_system_no_protagonist_state_extraction(self):
        """BATCH_EXTRACTION_SYSTEM exclut les jauges/crédits (gérés par narrator)"""
        assert "déjà gérés par le narrateur" in BATCH_EXTRACTION_SYSTEM

    def test_build_batch_prompt_basic(self):
        """build_batch_extraction_prompt inclut les paramètres"""
        prompt = build_batch_extraction_prompt(
            narrative_texts=["Valentin entre au café."],
            cycle=5,
            known_entities=["Ossek", "Marie"],
        )
        assert "Cycle: 5" in prompt
        assert "Ossek" in prompt
        assert "Valentin entre au café" in prompt
        assert "Arcs actifs: Aucun" in prompt

    def test_build_batch_prompt_with_known_arcs(self):
        """build_batch_extraction_prompt includes existing arc titles"""
        prompt = build_batch_extraction_prompt(
            narrative_texts=["Texte."],
            cycle=1,
            known_entities=[],
            known_arc_titles=["Bagages perdus", "Installation sur Chrysalide"],
        )
        assert "Bagages perdus" in prompt
        assert "Installation sur Chrysalide" in prompt
        assert "arcs_created QUE pour des arcs VRAIMENT nouveaux" in prompt

    def test_build_batch_prompt_with_inventory_hints(self):
        """build_batch_extraction_prompt inclut les inventory hints"""
        prompt = build_batch_extraction_prompt(
            narrative_texts=["Texte."],
            cycle=1,
            known_entities=[],
            inventory_hints=[{"item_name": "Clé", "action": "acquire"}],
        )
        assert "Clé" in prompt
        assert "acquire" in prompt

    def test_build_batch_prompt_with_narrator_hints(self):
        """build_batch_extraction_prompt agrège les signaux du narrateur"""
        prompt = build_batch_extraction_prompt(
            narrative_texts=["Texte."],
            cycle=1,
            known_entities=[],
            narrator_hints=[
                {"new_entities_mentioned": ["Alice"], "arc_advanced": ["Arc X"]},
                {"relationships_changed": True, "information_learned": True},
            ],
        )
        assert "Alice" in prompt
        assert "Arc X" in prompt
        assert "Relations modifiées" in prompt
        assert "Informations apprises" in prompt

    def test_example_keys_match_documented_keys(self):
        """Les clés dans les exemples JSON correspondent aux clés documentées"""
        from prompts.examples import (
            EXTRACTION_PROTAGONIST_STATE_EXAMPLE,
            EXTRACTION_ENTITIES_EXAMPLE,
            EXTRACTION_FACTS_EXAMPLE,
            EXTRACTION_RELATIONS_EXAMPLE,
            EXTRACTION_ARCS_EXAMPLE,
            EXTRACTION_OBJECTS_EXAMPLE,
        )

        assert set(EXTRACTION_PROTAGONIST_STATE_EXAMPLE.keys()) == {
            "gauge_changes", "credit_transactions", "inventory_changes"
        }
        assert set(EXTRACTION_ENTITIES_EXAMPLE.keys()) == {
            "entities_created", "entities_updated"
        }
        assert set(EXTRACTION_FACTS_EXAMPLE.keys()) == {"facts"}
        assert set(EXTRACTION_RELATIONS_EXAMPLE.keys()) == {
            "relations_created", "relations_updated"
        }
        assert set(EXTRACTION_ARCS_EXAMPLE.keys()) == {
            "arcs_created", "arcs_resolved", "events_scheduled"
        }
        assert set(EXTRACTION_OBJECTS_EXAMPLE.keys()) == {"objects_created"}
