"""
Tests unitaires pour state_normalizer.py
Priorité haute : c'est le cœur de la sérialisation frontend
"""

from decimal import Decimal
from uuid import UUID

from config import STATS_DEFAUT
from services.state_normalizer import (
    normalize_inventaire_item,
    normalize_valentin,
    normalize_partie,
    normalize_ia,
    normalize_game_state,
    merge_game_states,
    game_state_to_dict,
    InventaireItem,
    ValentinState,
    PartieState,
    IAState,
    GameState,
)


# =============================================================================
# TESTS INVENTAIRE
# =============================================================================


class TestNormalizeInventaireItem:
    """Tests pour normalize_inventaire_item"""

    def test_string_input(self):
        """Ancien format: juste un nom string"""
        item = normalize_inventaire_item("Lampe torche")
        assert item.nom == "Lampe torche"
        assert item.quantite == 1
        assert item.localisation == "sur_soi"
        assert item.categorie == "autre"

    def test_dict_input_french_keys(self):
        """Format dict avec clés françaises"""
        data = {
            "nom": "Carte d'accès",
            "quantite": 2,
            "localisation": "sac",
            "categorie": "outil",
            "etat": "usé",
        }
        item = normalize_inventaire_item(data)
        assert item.nom == "Carte d'accès"
        assert item.quantite == 2
        assert item.localisation == "sac"
        assert item.categorie == "outil"
        assert item.etat == "usé"

    def test_dict_input_english_keys(self):
        """Format dict avec clés anglaises (depuis BDD)"""
        data = {
            "name": "Access Card",
            "quantity": 3,
            "location": "pocket",
            "category": "tool",
            "condition": "good",
        }
        item = normalize_inventaire_item(data)
        assert item.nom == "Access Card"
        assert item.quantite == 3
        assert item.localisation == "pocket"
        assert item.categorie == "tool"
        assert item.etat == "good"

    def test_missing_fields_use_defaults(self):
        """Champs manquants → valeurs par défaut"""
        item = normalize_inventaire_item({"nom": "Truc"})
        assert item.quantite == 1
        assert item.localisation == "sur_soi"
        assert item.categorie == "autre"
        assert item.etat == "bon"

    def test_with_uuid(self):
        """Item avec UUID"""
        uid = UUID("12345678-1234-5678-1234-567812345678")
        item = normalize_inventaire_item({"id": uid, "nom": "Item"})
        assert item.id == uid


# =============================================================================
# TESTS VALENTIN
# =============================================================================


class TestNormalizeValentin:
    """Tests pour normalize_valentin"""

    def test_none_input(self):
        """None → valeurs par défaut"""
        state = normalize_valentin(None)
        assert state.energie == STATS_DEFAUT["energie"]
        assert state.moral == STATS_DEFAUT["moral"]
        assert state.sante == STATS_DEFAUT["sante"]
        assert state.credits == STATS_DEFAUT["credits"]
        assert state.inventaire == []

    def test_empty_dict(self):
        """Dict vide → valeurs par défaut"""
        state = normalize_valentin({})
        assert state.energie == STATS_DEFAUT["energie"]

    def test_french_keys(self):
        """Clés françaises"""
        state = normalize_valentin(
            {
                "energie": 3.5,
                "moral": 2.0,
                "sante": 4.5,
                "credits": 500,
            }
        )
        assert state.energie == 3.5
        assert state.moral == 2.0
        assert state.sante == 4.5
        assert state.credits == 500

    def test_english_keys(self):
        """Clés anglaises (depuis BDD)"""
        state = normalize_valentin(
            {
                "energy": 3.0,
                "health": 4.0,
            }
        )
        assert state.energie == 3.0
        assert state.sante == 4.0

    def test_decimal_conversion(self):
        """Decimal -> float"""
        state = normalize_valentin(
            {
                "energie": Decimal("3.75"),
                "moral": Decimal("2.50"),
            }
        )
        assert state.energie == 3.75
        assert isinstance(state.energie, float)
        assert state.moral == 2.50

    def test_with_inventaire_strings(self):
        """Inventaire avec ancien format (strings)"""
        state = normalize_valentin({"inventaire": ["Lampe", "Clé", "Carte"]})
        assert len(state.inventaire) == 3
        assert state.inventaire[0].nom == "Lampe"
        assert state.inventaire[1].nom == "Clé"

    def test_with_inventaire_dicts(self):
        """Inventaire avec nouveau format (dicts)"""
        state = normalize_valentin(
            {
                "inventaire": [
                    {"nom": "Lampe", "quantite": 1},
                    {"nom": "Clé", "quantite": 2},
                ]
            }
        )
        assert len(state.inventaire) == 2
        assert state.inventaire[1].quantite == 2


# =============================================================================
# TESTS PARTIE
# =============================================================================


class TestNormalizePartie:
    """Tests pour normalize_partie"""

    def test_none_input(self):
        """None → None"""
        assert normalize_partie(None) is None

    def test_minimal_input(self):
        """Input minimal"""
        partie = normalize_partie({"nom": "Ma partie"})
        assert partie.nom == "Ma partie"
        assert partie.cycle_actuel == 1
        assert partie.status == "active"

    def test_french_keys(self):
        """Clés françaises"""
        partie = normalize_partie(
            {
                "nom": "Aventure",
                "cycle_actuel": 5,
                "date_jeu": "Lundi 3 janvier",
                "heure": "14h30",
                "lieu_actuel": "Bar du port",
            }
        )
        assert partie.cycle_actuel == 5
        assert partie.date_jeu == "Lundi 3 janvier"
        assert partie.heure == "14h30"
        assert partie.lieu_actuel == "Bar du port"

    def test_english_keys(self):
        """Clés anglaises (depuis BDD)"""
        partie = normalize_partie(
            {
                "name": "Adventure",
                "current_cycle": 3,
                "universe_date": "Monday",
                "current_location": "Dock",
            }
        )
        assert partie.nom == "Adventure"
        assert partie.cycle_actuel == 3
        assert partie.date_jeu == "Monday"
        assert partie.lieu_actuel == "Dock"

    def test_pnjs_presents(self):
        """Liste des PNJs présents"""
        partie = normalize_partie({"pnjs_presents": ["Alice", "Bob"]})
        assert partie.pnjs_presents == ["Alice", "Bob"]


# =============================================================================
# TESTS IA
# =============================================================================


class TestNormalizeIA:
    """Tests pour normalize_ia"""

    def test_none_input(self):
        """None → None"""
        assert normalize_ia(None) is None

    def test_minimal_input(self):
        """Input minimal"""
        ia = normalize_ia({"nom": "ARIA"})
        assert ia.nom == "ARIA"
        assert ia.personnalite == []

    def test_personnalite_as_list(self):
        """Personnalité en liste"""
        ia = normalize_ia(
            {"nom": "ARIA", "personnalite": ["sarcastique", "loyale", "curieuse"]}
        )
        assert ia.personnalite == ["sarcastique", "loyale", "curieuse"]

    def test_personnalite_as_string(self):
        """Personnalité en string (ancien format) → liste"""
        ia = normalize_ia({"nom": "ARIA", "personnalite": "sarcastique"})
        assert ia.personnalite == ["sarcastique"]

    def test_english_keys(self):
        """Clés anglaises"""
        ia = normalize_ia(
            {
                "name": "ARIA",
                "personality": ["sarcastic"],
                "voice": "warm",
                "relationship_level": 5,
            }
        )
        assert ia.nom == "ARIA"
        assert ia.voix == "warm"
        assert ia.relation == 5


# =============================================================================
# TESTS GAME STATE COMPLET
# =============================================================================


class TestNormalizeGameState:
    """Tests pour normalize_game_state"""

    def test_empty_input(self):
        """Aucune donnée → état par défaut"""
        state = normalize_game_state()
        assert state.partie is None
        assert state.valentin.energie == STATS_DEFAUT["energie"]
        assert state.ia is None

    def test_structured_input(self):
        """Input structuré (partie_data, valentin_data, ia_data)"""
        state = normalize_game_state(
            partie_data={"nom": "Test", "cycle_actuel": 2},
            valentin_data={"energie": 3.0, "credits": 1000},
            ia_data={"nom": "ARIA"},
        )
        assert state.partie.nom == "Test"
        assert state.partie.cycle_actuel == 2
        assert state.valentin.energie == 3.0
        assert state.valentin.credits == 1000
        assert state.ia.nom == "ARIA"

    def test_flat_input_already_structured(self):
        """flat_data déjà structuré avec clés partie/valentin"""
        state = normalize_game_state(
            flat_data={
                "partie": {"nom": "Flat Test"},
                "valentin": {"credits": 500},
                "ia": {"nom": "BOT"},
            }
        )
        assert state.partie.nom == "Flat Test"
        assert state.valentin.credits == 500
        assert state.ia.nom == "BOT"

    def test_flat_input_raw(self):
        """flat_data brut (depuis BDD directement)"""
        state = normalize_game_state(
            flat_data={
                "nom": "Direct",
                "energie": 2.5,
                "credits": 800,
            }
        )
        assert state.valentin.energie == 2.5
        assert state.valentin.credits == 800


# =============================================================================
# TESTS MERGE
# =============================================================================


class TestMergeGameStates:
    """Tests pour merge_game_states"""

    def test_merge_partial_update(self):
        """Mise à jour partielle"""
        prev = GameState(
            partie=PartieState(nom="Test", cycle_actuel=1, lieu_actuel="Bar"),
            valentin=ValentinState(energie=4.0, credits=1000),
        )
        merged = merge_game_states(prev, {"partie": {"cycle_actuel": 2}})

        # Valeurs mises à jour
        assert merged.partie.cycle_actuel == 2
        # Valeurs préservées
        assert merged.partie.nom == "Test"
        assert merged.partie.lieu_actuel == "Bar"
        assert merged.valentin.credits == 1000

    def test_merge_preserves_ia(self):
        """Merge préserve l'IA si pas dans l'update"""
        prev = GameState(
            valentin=ValentinState(),
            ia=IAState(nom="ARIA", personnalite=["cool"]),
        )
        merged = merge_game_states(prev, {"valentin": {"credits": 500}})

        assert merged.ia.nom == "ARIA"
        assert merged.ia.personnalite == ["cool"]


# =============================================================================
# TESTS SERIALIZATION
# =============================================================================


class TestGameStateToDict:
    """Tests pour game_state_to_dict"""

    def test_excludes_none(self):
        """Les None sont exclus du dict"""
        state = GameState(
            partie=PartieState(nom="Test"),
            valentin=ValentinState(),
        )
        d = game_state_to_dict(state)

        # ia est None, ne doit pas apparaître
        assert "ia" not in d or d.get("ia") is None

    def test_serializes_inventaire(self):
        """L'inventaire est bien sérialisé"""
        state = GameState(
            valentin=ValentinState(inventaire=[InventaireItem(nom="Clé", quantite=2)]),
        )
        d = game_state_to_dict(state)

        assert len(d["valentin"]["inventaire"]) == 1
        assert d["valentin"]["inventaire"][0]["nom"] == "Clé"
        assert d["valentin"]["inventaire"][0]["quantite"] == 2

    def test_uuid_serialization(self):
        """Les UUID sont convertis en string"""
        uid = UUID("12345678-1234-5678-1234-567812345678")
        state = GameState(
            partie=PartieState(id=uid, nom="Test"),
            valentin=ValentinState(),
        )
        d = game_state_to_dict(state)

        # Pydantic mode="json" convertit UUID en string
        assert d["partie"]["id"] == str(uid)
