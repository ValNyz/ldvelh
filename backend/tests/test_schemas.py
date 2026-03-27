"""
Tests des schémas Pydantic avec les exemples JSON importés depuis prompts/examples.py
Vérifie que les exemples donnés au LLM sont valides selon nos schémas.
"""

import pytest
from pydantic import ValidationError

from schema import (
    # Entities
    WorldData,
    LocationData,
    CharacterData,
    OrganizationData,
    ProtagonistData,
    PersonalAIData,
    ObjectData,
    # Narration
    NarrationOutput,
    NarrationHints,
    TimeProgression,
    DayTransition,
    # Extraction
    NarrativeExtraction,
    EntityCreation,
    EntityUpdate,
    GaugeChange,
    CreditTransaction,
    InventoryChange,
    RelationCreation,
    RelationUpdate,
    FactData,
    CommitmentCreationExtraction,
    CommitmentResolutionExtraction,
    EventScheduledExtraction,
    ObjectCreation,
    NarrativeArcData,
    # Core
    AttributeKey,
    EntityType,
    RelationType,
    FactType,
    Skill,
    # Relations
    RelationData,
    # Normalizers
    normalize_entity_type,
    normalize_relation_type,
    normalize_fact_type,
    normalize_attribute_key,
)

# Import direct des exemples pour les tests paramétrés


# =============================================================================
# WORLD GENERATION - Tests de l'exemple complet
# =============================================================================


class TestWorldGenerationExample:
    """Teste que l'exemple COMPLET de world_generation_prompt est valide"""

    def test_world_data(self, world_generation_example):
        """WorldData parse correctement"""
        world = WorldData(**world_generation_example["world"])
        assert world.name == "Escale Méridienne"
        assert len(world.sectors) == 3
        assert world.founding_cycle == -4500
        assert len(world.attributes) == 4

    def test_all_locations(self, world_generation_example):
        """Tous les LocationData parsent correctement"""
        locations = world_generation_example["locations"]
        assert len(locations) == 5

        for loc_data in locations:
            loc = LocationData(**loc_data)
            assert loc.name
            assert len(loc.attributes) > 0

    def test_location_with_parent_ref(self, world_generation_example):
        """LocationData avec parent_location_ref"""
        # Appartement 4-12 a un parent
        apt = next(
            l
            for l in world_generation_example["locations"]
            if l["name"] == "Appartement 4-12"
        )
        loc = LocationData(**apt)
        assert loc.parent_location_ref == "Bloc Tournesol"

    def test_all_organizations(self, world_generation_example):
        """Tous les OrganizationData parsent correctement"""
        for org_data in world_generation_example["organizations"]:
            org = OrganizationData(**org_data)
            assert org.name == "Symbiose Tech"
            assert org.headquarters_ref == "Serres Hydro-7"

    def test_protagonist(self, world_generation_example):
        """ProtagonistData parse correctement"""
        protag = ProtagonistData(**world_generation_example["protagonist"])
        assert protag.name == "Valentin"
        assert len(protag.skills) == 2
        assert protag.skills[0].level == 4
        assert protag.skills[0].name == "architecture_systemes"

    def test_personal_ai(self, world_generation_example):
        """PersonalAIData parse correctement"""
        ai = PersonalAIData(**world_generation_example["personal_ai"])
        assert ai.name == "Célimène"
        assert len(ai.attributes) == 4

    def test_all_characters(self, world_generation_example):
        """Tous les CharacterData parsent correctement"""
        chars = world_generation_example["characters"]
        assert len(chars) == 3

        for char_data in chars:
            char = CharacterData(**char_data)
            assert char.name
            assert char.known_by_protagonist is False

    def test_character_with_arcs(self, world_generation_example):
        """CharacterData avec arcs dans attributes"""
        justine_data = world_generation_example["characters"][0]
        justine = CharacterData(**justine_data)
        assert justine.name == "Justine Lépicier"
        # Vérifie que l'attribut arcs existe
        arcs_attr = next(
            (a for a in justine.attributes if a.key == AttributeKey.ARCS), None
        )
        assert arcs_attr is not None
        assert "family" in arcs_attr.value  # domain family dans le JSON

    def test_character_alien_species(self, world_generation_example):
        """CharacterData avec espèce non-humaine"""
        ossek_data = world_generation_example["characters"][2]
        ossek = CharacterData(**ossek_data)
        assert ossek.name == "Ossek"
        species_attr = next(
            (a for a in ossek.attributes if a.key == AttributeKey.SPECIES), None
        )
        assert species_attr is not None
        assert "keth" in species_attr.value.lower()

    def test_all_inventory(self, world_generation_example):
        """Tous les ObjectData parsent correctement"""
        for obj_data in world_generation_example["inventory"]:
            obj = ObjectData(**obj_data)
            assert obj.name
            assert obj.quantity >= 1

    def test_narrative_arcs(self, world_generation_example):
        """NarrativeArcData parse correctement"""
        for arc_data in world_generation_example["narrative_arcs"]:
            arc = NarrativeArcData(**arc_data)
            assert arc.title == "Pression sur Symbiose"
            assert arc.arc_type.value == "foreshadowing"
            assert len(arc.potential_triggers) >= 1

    def test_all_relations(self, world_generation_example):
        """Toutes les RelationData parsent correctement"""
        relations = world_generation_example["initial_relations"]
        assert len(relations) == 9

        for rel_data in relations:
            rel = RelationData(**rel_data)
            assert rel.source_ref
            assert rel.target_ref
            assert rel.relation_type in RelationType


# =============================================================================
# NARRATION - Tests des 3 exemples
# =============================================================================


class TestNarrationExamples:
    """Teste les exemples du narrator_prompt"""

    def test_example_neutral_scene(self, narration_examples):
        """Exemple 1: Scène neutre"""
        output = NarrationOutput(**narration_examples["neutral"])
        assert "Quart de Cycle" in output.narrative_text
        assert output.time.new_time == "10h15"
        assert output.time.ellipse is False
        assert output.current_location == "Le Quart de Cycle"
        assert output.npcs_present == ["Ossek"]
        assert len(output.suggested_actions) == 3
        assert output.scene_mood == "banal et indifférent"
        assert output.hints.needs_extraction is False

    def test_example_pnj_unavailable(self, narration_examples):
        """Exemple 2: PNJ indisponible avec commitment_advanced"""
        output = NarrationOutput(**narration_examples["pnj_unavailable"])
        assert output.time.new_time == "10h20"
        assert len(output.suggested_actions) == 4
        assert output.hints.commitment_advanced == ["L'exil du banc"]
        assert output.hints.needs_extraction is True
        assert output.narrator_notes == "Ossek: mauvaise journée (mal du banc)"

    def test_example_day_transition(self, narration_examples):
        """Exemple 3: Transition de jour"""
        output = NarrationOutput(**narration_examples["day_transition"])
        assert output.day_transition is not None
        assert output.day_transition.new_cycle == 5
        assert output.day_transition.new_date == "Samedi 18 Mars 2847"
        assert output.day_transition.night_summary == "Nuit agitée, rêves confus."
        assert output.npcs_present == []

    def test_template_structure(self, narration_examples):
        """Template pour le prompt parse correctement"""
        output = NarrationOutput(**narration_examples["template"])
        assert output.time.new_time == "14h45"
        assert output.scene_mood == "2-4 mots max"


class TestNarrationSubModels:
    """Teste les sous-modèles de narration"""

    def test_time_progression(self):
        """TimeProgression parse correctement"""
        time = TimeProgression(new_time="14h30", ellipse=False)
        assert time.new_time == "14h30"

    def test_time_progression_with_ellipse(self):
        """TimeProgression avec ellipse"""
        time = TimeProgression(
            new_time="18h00", ellipse=True, ellipse_summary="Quelques heures passent..."
        )
        assert time.ellipse is True
        assert time.ellipse_summary is not None

    def test_day_transition(self):
        """DayTransition parse correctement"""
        dt = DayTransition(
            new_cycle=5, new_date="Samedi 18 Mars 2847", night_summary="Nuit agitée"
        )
        assert dt.new_cycle == 5


# =============================================================================
# EXTRACTION - Tests de tous les exemples
# =============================================================================


class TestExtractionExamples:
    """Teste tous les exemples des prompts d'extraction"""

    def test_gauge_changes(self, extraction_examples):
        """GaugeChange parse correctement"""
        for gc in extraction_examples["protagonist_state"]["gauge_changes"]:
            change = GaugeChange(**gc)
            assert change.gauge == "energy"
            assert change.delta == -0.5
            assert change.reason == "Conversation épuisante"

    def test_credit_transactions(self, extraction_examples):
        """CreditTransaction parse correctement"""
        for ct in extraction_examples["protagonist_state"]["credit_transactions"]:
            tx = CreditTransaction(**ct)
            assert tx.amount == -15
            assert "Café" in tx.description

    def test_inventory_changes_acquire(self, extraction_examples):
        """InventoryChange acquire avec object_hint"""
        for ic in extraction_examples["protagonist_state"]["inventory_changes"]:
            change = InventoryChange(**ic)
            assert change.action == "acquire"
            assert change.object_hint == "Carte d'accès temporaire"
            assert change.quantity_delta == 1

    def test_entity_creation(self, extraction_examples):
        """EntityCreation parse correctement"""
        for ec in extraction_examples["entities"]["entities_created"]:
            entity = EntityCreation(**ec)
            assert entity.name == "Elena Vasquez"
            assert entity.entity_type == EntityType.CHARACTER
            assert entity.known_by_protagonist is True
            assert len(entity.attributes) >= 3

    def test_entity_update(self, extraction_examples):
        """EntityUpdate parse correctement"""
        for eu in extraction_examples["entities"]["entities_updated"]:
            update = EntityUpdate(**eu)
            assert update.entity_ref == "La femme mystérieuse"
            assert update.now_known is True
            assert update.real_name == "Dr. Sarah Chen"

    def test_facts_with_semantic_key(self, extraction_examples):
        """FactData avec semantic_key"""
        for f in extraction_examples["facts"]["facts"]:
            # Ajouter cycle qui est requis
            fact_data = {**f, "cycle": 5}
            fact = FactData(**fact_data)
            assert fact.fact_type == FactType.REVELATION
            assert fact.semantic_key == "marie:revele:mere_malade"
            assert fact.importance == 4
            assert len(fact.participants) == 2

    def test_relation_creation(self, extraction_examples):
        """RelationCreation parse correctement"""
        for rc in extraction_examples["relations"]["relations_created"]:
            rel = RelationCreation(**rc)
            assert rel.cycle == 5
            assert rel.relation.relation_type == RelationType.KNOWS
            assert rel.relation.social is not None
            assert rel.relation.social.level == 3

    def test_relation_update(self, extraction_examples):
        """RelationUpdate parse correctement"""
        for ru in extraction_examples["relations"]["relations_updated"]:
            update = RelationUpdate(**ru)
            assert update.new_level == 4
            assert update.new_context == "Confidents"

    def test_commitment_creation(self, extraction_examples):
        """CommitmentCreationExtraction parse correctement"""
        for cc in extraction_examples["commitments"]["commitments_created"]:
            commitment = CommitmentCreationExtraction(**cc)
            assert commitment.commitment_type.value == "foreshadowing"
            assert "Marie" in commitment.involved_entities

    def test_commitment_resolution(self, extraction_examples):
        """CommitmentResolutionExtraction parse correctement"""
        for cr in extraction_examples["commitments"]["commitments_resolved"]:
            resolution = CommitmentResolutionExtraction(**cr)
            assert "rapport" in resolution.commitment_description.lower()

    def test_event_scheduled(self, extraction_examples):
        """EventScheduledExtraction parse correctement"""
        for ev in extraction_examples["commitments"]["events_scheduled"]:
            event = EventScheduledExtraction(**ev)
            assert event.title == "Déjeuner avec Marie"
            assert event.planned_cycle == 7
            assert event.time == "12h30"
            assert event.location_ref == "Le Quart de Cycle"

    def test_object_creation(self, extraction_examples):
        """ObjectCreation parse correctement"""
        for oc in extraction_examples["objects"]["objects_created"]:
            obj = ObjectCreation(**oc)
            assert obj.name == "Carte d'accès niveau 2"
            assert obj.from_hint == "Carte d'accès temporaire"

    def test_full_extraction(self, extraction_examples):
        """NarrativeExtraction complet parse correctement"""
        # L'exemple full utilise les facts sans cycle, on doit les enrichir
        full = extraction_examples["full"].copy()
        # Ajouter cycle aux facts
        full["facts"] = [{**f, "cycle": full["cycle"]} for f in full["facts"]]
        extraction = NarrativeExtraction(**full)
        assert extraction.cycle == 5
        assert extraction.current_location_ref == "Le Quart de Cycle"
        assert len(extraction.facts) >= 1
        assert len(extraction.entities_created) >= 1
        assert extraction.segment_summary != ""


# =============================================================================
# NORMALIZERS - Tests des synonymes LLM
# =============================================================================


class TestNormalizers:
    """Teste les fonctions de normalisation avec synonymes"""

    @pytest.mark.parametrize(
        "input_val,expected",
        [
            ("character", "character"),
            ("CHARACTER", "character"),
            ("pnj", "character"),
            ("npc", "character"),
            ("personnage", "character"),
            ("person", "character"),
            ("location", "location"),
            ("lieu", "location"),
            ("place", "location"),
            ("object", "object"),
            ("objet", "object"),
            ("item", "object"),
            ("organization", "organization"),
            ("organisation", "organization"),
            ("org", "organization"),
            ("company", "organization"),
        ],
    )
    def test_normalize_entity_type(self, input_val, expected):
        """normalize_entity_type gère les synonymes FR/EN"""
        assert normalize_entity_type(input_val) == expected

    @pytest.mark.parametrize(
        "input_val,expected",
        [
            ("knows", "knows"),
            ("connait", "knows"),
            ("friend_of", "friend_of"),
            ("ami", "friend_of"),
            ("employed_by", "employed_by"),
            ("works_for", "employed_by"),
            ("lives_at", "lives_at"),
            ("habite", "lives_at"),
            ("owns", "owns"),
        ],
    )
    def test_normalize_relation_type(self, input_val, expected):
        """normalize_relation_type gère les synonymes FR/EN"""
        assert normalize_relation_type(input_val) == expected

    @pytest.mark.parametrize(
        "input_val,expected",
        [
            ("revelation", "revelation"),
            ("action", "action"),
            ("observation", "observation"),
            ("encounter", "encounter"),
            ("rencontre", "encounter"),
            ("promise", "promise"),
        ],
    )
    def test_normalize_fact_type(self, input_val, expected):
        """normalize_fact_type gère les synonymes"""
        assert normalize_fact_type(input_val) == expected


class TestAttributeKeys:
    """Teste la normalisation des clés d'attributs"""

    @pytest.mark.parametrize(
        "input_key,expected",
        [
            ("description", AttributeKey.DESCRIPTION),
            ("desc", AttributeKey.DESCRIPTION),
            ("mood", AttributeKey.MOOD),
            ("humeur", AttributeKey.MOOD),
            ("atmosphere", AttributeKey.ATMOSPHERE),
            ("ambiance", AttributeKey.ATMOSPHERE),
            ("sector", AttributeKey.SECTOR),
            ("secteur", AttributeKey.SECTOR),
            ("occupation", AttributeKey.OCCUPATION),
            ("job", AttributeKey.OCCUPATION),
            ("traits", AttributeKey.TRAITS),
            ("personality", AttributeKey.TRAITS),
        ],
    )
    def test_normalize_attribute_key(self, input_key, expected):
        """normalize_attribute_key gère les synonymes"""
        assert normalize_attribute_key(input_key) == expected

    def test_invalid_key_raises(self):
        """Clé invalide lève une exception"""
        with pytest.raises(ValueError):
            normalize_attribute_key("invalid_key_xyz_123")


# =============================================================================
# VALIDATION ERRORS - Tests des rejets
# =============================================================================


class TestValidationErrors:
    """Teste que les validations Pydantic fonctionnent"""

    def test_gauge_change_invalid_gauge(self):
        """GaugeChange rejette les jauges invalides"""
        with pytest.raises(ValidationError):
            GaugeChange(gauge="invalid", delta=1, reason="test")

    def test_gauge_change_delta_bounds(self):
        """GaugeChange respecte les bornes [-5, 5]"""
        GaugeChange(gauge="energy", delta=5, reason="max")
        GaugeChange(gauge="energy", delta=-5, reason="min")
        with pytest.raises(ValidationError):
            GaugeChange(gauge="energy", delta=10, reason="trop")

    def test_inventory_change_acquire_validation(self):
        """InventoryChange.acquire nécessite ref ou hint"""
        with pytest.raises(ValidationError):
            InventoryChange(action="acquire")

    def test_inventory_change_lose_requires_ref(self):
        """InventoryChange.lose nécessite object_ref"""
        with pytest.raises(ValidationError):
            InventoryChange(action="lose", object_hint="x")

    def test_fact_semantic_key_format(self):
        """FactData.semantic_key format sujet:verbe:objet"""
        FactData(
            cycle=1,
            fact_type="observation",
            description="Test",
            semantic_key="a:b:c",
            importance=3,
        )
        with pytest.raises(ValidationError):
            FactData(
                cycle=1,
                fact_type="observation",
                description="Test",
                semantic_key="invalid",
                importance=3,
            )

    def test_skill_level_bounds(self):
        """Skill.level entre 1 et 5"""
        Skill(name="test", level=1)
        Skill(name="test", level=5)
        with pytest.raises(ValidationError):
            Skill(name="test", level=0)
        with pytest.raises(ValidationError):
            Skill(name="test", level=6)

    def test_world_founding_cycle_negative(self):
        """WorldData.founding_cycle <= -100"""
        with pytest.raises(ValidationError):
            WorldData(name="X", attributes=[], sectors=["A", "B"], founding_cycle=0)


# =============================================================================
# NARRATION HINTS - Tests needs_extraction
# =============================================================================


class TestNarrationHintsNeedsExtraction:
    """Teste la propriété needs_extraction"""

    def test_all_false_returns_false(self):
        """Tous hints False → needs_extraction = False"""
        hints = NarrationHints()
        assert hints.needs_extraction is False

    @pytest.mark.parametrize(
        "field,value",
        [
            ("new_entities_mentioned", ["Test"]),
            ("relationships_changed", True),
            ("protagonist_state_changed", True),
            ("information_learned", True),
            ("commitment_advanced", ["Arc"]),
            ("commitment_resolved", ["Arc"]),
            ("new_commitment_created", True),
            ("event_scheduled", True),
            ("event_occurred", True),
        ],
    )
    def test_single_true_triggers(self, field, value):
        """Un seul hint True → needs_extraction = True"""
        hints = NarrationHints(**{field: value})
        assert hints.needs_extraction is True


# =============================================================================
# STRING TRUNCATION
# =============================================================================


class TestStringTruncation:
    """Teste la troncation automatique des strings"""

    def test_long_description_truncated(self):
        """Descriptions > 500 chars tronquées"""
        very_long = "A" * 1000
        obj = ObjectData(
            name="Test",
            attributes=[{"key": "description", "value": very_long, "known": True}],
        )
        assert len(obj.attributes[0].value) <= 500
        assert obj.attributes[0].value.endswith("...")

    def test_name_truncated_at_100(self):
        """Noms > 100 chars tronqués"""
        long_name = "A" * 200
        loc = LocationData(name=long_name, attributes=[])
        assert len(loc.name) <= 100
