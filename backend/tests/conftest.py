"""
Configuration pytest et fixtures partagées
Importe les exemples depuis prompts/examples.py
"""

import sys
from pathlib import Path

import pytest

# Ajouter le dossier backend au path pour les imports
backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

# Configurer le logging pour les tests (moins verbeux)
import logging

logging.basicConfig(level=logging.WARNING)


# =============================================================================
# FIXTURES - Exemples importés depuis prompts/examples.py
# =============================================================================

from prompts.examples import (
    # World Generation
    WORLD_GENERATION_EXAMPLE,
    # Narration
    NARRATION_EXAMPLE_NEUTRAL,
    NARRATION_EXAMPLE_PNJ_UNAVAILABLE,
    NARRATION_EXAMPLE_DAY_TRANSITION,
    NARRATION_OUTPUT_TEMPLATE,
    # Extraction
    EXTRACTION_PROTAGONIST_STATE_EXAMPLE,
    EXTRACTION_ENTITIES_EXAMPLE,
    EXTRACTION_FACTS_EXAMPLE,
    EXTRACTION_RELATIONS_EXAMPLE,
    EXTRACTION_COMMITMENTS_EXAMPLE,
    EXTRACTION_OBJECTS_EXAMPLE,
)


@pytest.fixture
def world_generation_example():
    """Exemple complet de génération de monde"""
    return WORLD_GENERATION_EXAMPLE


@pytest.fixture
def narration_examples():
    """Tous les exemples de narration"""
    return {
        "neutral": NARRATION_EXAMPLE_NEUTRAL,
        "pnj_unavailable": NARRATION_EXAMPLE_PNJ_UNAVAILABLE,
        "day_transition": NARRATION_EXAMPLE_DAY_TRANSITION,
        "template": NARRATION_OUTPUT_TEMPLATE,
    }


@pytest.fixture
def extraction_examples():
    """Tous les exemples d'extraction"""
    return {
        "protagonist_state": EXTRACTION_PROTAGONIST_STATE_EXAMPLE,
        "entities": EXTRACTION_ENTITIES_EXAMPLE,
        "facts": EXTRACTION_FACTS_EXAMPLE,
        "relations": EXTRACTION_RELATIONS_EXAMPLE,
        "commitments": EXTRACTION_COMMITMENTS_EXAMPLE,
        "objects": EXTRACTION_OBJECTS_EXAMPLE,
    }


# =============================================================================
# FIXTURES - Données de test réutilisables
# =============================================================================


@pytest.fixture
def sample_game_state():
    """État de jeu pour tests du state_normalizer"""
    return {
        "partie": {
            "nom": "Test Adventure",
            "cycle_actuel": 3,
            "date_jeu": "Mardi 2 janvier 2475",
            "heure": "14h30",
            "lieu_actuel": "Le Quart de Cycle",
            "pnjs_presents": ["Marie", "Jean"],
        },
        "valentin": {
            "energie": 3.5,
            "moral": 4.0,
            "sante": 5.0,
            "credits": 1200,
            "inventaire": [
                {"nom": "Communicateur", "quantite": 1},
            ],
        },
        "ia": {
            "nom": "Célimène",
            "personnalite": ["sarcastique", "loyale"],
            "quirk": "Fait des références obscures",
        },
    }


@pytest.fixture
def sample_narration_context():
    """Contexte de narration minimal pour tests"""
    from schema import (
        NarrationContext,
        LocationSummary,
        ProtagonistState,
        GaugeState,
    )

    return NarrationContext(
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


# =============================================================================
# MARKERS
# =============================================================================


def pytest_configure(config):
    """Ajoute des markers personnalisés"""
    config.addinivalue_line("markers", "slow: marque les tests lents")
    config.addinivalue_line(
        "markers", "integration: marque les tests d'intégration (nécessite BDD)"
    )
