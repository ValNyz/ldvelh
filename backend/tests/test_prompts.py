"""
Tests des fonctions utilitaires dans les prompts.
Pas de LLM, juste logique pure.
"""

from prompts.extractor_prompts import (
    should_run_extraction,
    get_minimal_extraction,
    extract_object_hints,
    build_summary_prompt,
    build_protagonist_state_prompt,
    build_facts_prompt,
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

    def test_commitment_advanced_triggers_extraction(self):
        """Arc avancé → extraction"""
        hints = NarrationHints(commitment_advanced=["Arc de Marie"])
        assert should_run_extraction(hints) is True

    def test_commitment_resolved_triggers_extraction(self):
        """Arc résolu → extraction"""
        hints = NarrationHints(commitment_resolved=["Promesse tenue"])
        assert should_run_extraction(hints) is True

    def test_new_commitment_triggers_extraction(self):
        """Nouvel engagement → extraction"""
        hints = NarrationHints(new_commitment_created=True)
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
# TESTS get_minimal_extraction
# =============================================================================


class TestGetMinimalExtraction:
    """Teste la génération d'extraction minimale"""

    def test_returns_correct_structure(self):
        """Retourne la structure attendue"""
        result = get_minimal_extraction(
            cycle=5,
            location="Le Quart de Cycle",
            npcs=["Ossek", "Marie"],
            summary="Valentin boit un café",
        )

        assert result["cycle"] == 5
        assert result["current_location_ref"] == "Le Quart de Cycle"
        assert result["segment_summary"] == "Valentin boit un café"
        assert result["key_npcs_present"] == ["Ossek", "Marie"]

    def test_empty_lists_by_default(self):
        """Les listes sont vides par défaut"""
        result = get_minimal_extraction(1, "Lieu", [], "Résumé")

        assert result["facts"] == []
        assert result["entities_created"] == []
        assert result["gauge_changes"] == []
        assert result["inventory_changes"] == []
        assert result["relations_created"] == []

    def test_all_expected_keys_present(self):
        """Toutes les clés attendues sont présentes"""
        result = get_minimal_extraction(1, "Lieu", [], "Résumé")

        expected_keys = [
            "cycle",
            "current_location_ref",
            "facts",
            "entities_created",
            "entities_updated",
            "relations_created",
            "relations_updated",
            "gauge_changes",
            "credit_transactions",
            "inventory_changes",
            "commitments_created",
            "commitments_resolved",
            "events_scheduled",
            "segment_summary",
            "key_npcs_present",
        ]

        for key in expected_keys:
            assert key in result, f"Missing key: {key}"


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
# TESTS PROMPT BUILDERS
# =============================================================================


class TestPromptBuilders:
    """Teste que les prompt builders génèrent du contenu valide"""

    def test_build_summary_prompt(self):
        """build_summary_prompt inclut le texte"""
        text = "Valentin entre dans le café."
        prompt = build_summary_prompt(text)

        assert text in prompt
        assert "Résume" in prompt
        assert "JSON" in prompt

    def test_build_protagonist_state_prompt(self):
        """build_protagonist_state_prompt inclut le contexte"""
        text = "Valentin achète un café."
        objects = ["Lampe", "Terminal"]
        prompt = build_protagonist_state_prompt(text, objects)

        assert text in prompt
        assert "Lampe" in prompt
        assert "Terminal" in prompt

    def test_build_protagonist_state_prompt_no_objects(self):
        """build_protagonist_state_prompt gère la liste vide"""
        prompt = build_protagonist_state_prompt("Texte", None)
        assert "Aucun connu" in prompt

    def test_build_facts_prompt(self):
        """build_facts_prompt inclut tous les paramètres"""
        prompt = build_facts_prompt(
            narrative_text="Valentin discute avec Marie.",
            cycle=5,
            location="Le Quart de Cycle",
            known_entities=["Marie", "Ossek"],
        )

        assert "Valentin discute" in prompt
        assert "Cycle: 5" in prompt
        assert "Le Quart de Cycle" in prompt
        assert "Marie" in prompt
        assert "Ossek" in prompt

    def test_build_facts_prompt_empty_entities(self):
        """build_facts_prompt gère la liste vide d'entités"""
        prompt = build_facts_prompt("Texte", 1, "Lieu", [])
        assert "Aucune" in prompt


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

    def test_build_narrator_context_prompt_basic(self):
        """Le builder génère un prompt valide"""
        from prompts.narrator_prompt import build_narrator_context_prompt
        from schema import (
            NarrationContext,
            LocationSummary,
            ProtagonistState,
            GaugeState,
        )

        context = NarrationContext(
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
# TESTS EXTRACTOR PROMPT BUILDERS
# =============================================================================


class TestExtractorPromptBuilders:
    """Teste tous les builders de prompts d'extraction"""

    def test_build_entities_prompt(self):
        """build_entities_prompt inclut les paramètres"""
        from prompts.extractor_prompts import build_entities_prompt

        prompt = build_entities_prompt(
            narrative_text="Valentin rencontre Marie.",
            new_entities_hints=["Marie", "Le bar"],
            known_entities=["Ossek", "Justine"],
        )

        assert "Valentin rencontre Marie" in prompt
        assert "Marie" in prompt
        assert "Le bar" in prompt
        assert "Ossek" in prompt
        assert "DÉJÀ CONNUES" in prompt

    def test_build_relations_prompt(self):
        """build_relations_prompt inclut le cycle et les entités"""
        from prompts.extractor_prompts import build_relations_prompt

        prompt = build_relations_prompt(
            narrative_text="Ils discutent longuement.",
            cycle=5,
            known_entities=["Marie", "Valentin"],
        )

        assert "Cycle: 5" in prompt
        assert "Marie" in prompt
        assert "Valentin" in prompt

    def test_build_commitments_prompt(self):
        """build_commitments_prompt inclut les hints"""
        from prompts.extractor_prompts import build_commitments_prompt

        prompt = build_commitments_prompt(
            narrative_text="Marie promet de revenir.",
            known_entities=["Marie"],
            commitment_hints=["Promesse de Marie"],
        )

        assert "Marie promet" in prompt
        assert "Promesse de Marie" in prompt

    def test_build_objects_prompt(self):
        """build_objects_prompt inclut les hints d'objets"""
        from prompts.extractor_prompts import build_objects_prompt

        prompt = build_objects_prompt(
            narrative_text="Il lui donne une clé.",
            object_hints=["Clé magnétique", "Badge d'accès"],
        )

        assert "Clé magnétique" in prompt
        assert "Badge d'accès" in prompt

    def test_build_extractor_prompt_full(self):
        """build_extractor_prompt génère un prompt complet"""
        from prompts.extractor_prompts import build_extractor_prompt

        prompt = build_extractor_prompt(
            narrative_text="Valentin entre dans le café.",
            hints=NarrationHints(
                new_entities_mentioned=["Nouveau PNJ"],
                protagonist_state_changed=True,
            ),
            current_cycle=3,
            current_location="Le Quart de Cycle",
            npcs_present=["Ossek"],
            known_entities=["Justine", "Marie"],
        )

        assert "TEXTE À ANALYSER" in prompt
        assert "Valentin entre" in prompt
        assert "Cycle: 3" in prompt
        assert "Le Quart de Cycle" in prompt
        assert "Nouveau PNJ" in prompt
        assert "État protagoniste modifié" in prompt
