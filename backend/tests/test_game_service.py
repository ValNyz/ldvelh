"""
Tests unitaires pour game_service.py
Focus sur les helpers statiques (logique pure)
"""

import pytest
from services.game_service import GameService


class TestGetRelationLabel:
    """Tests pour _get_relation_label"""

    def test_none_returns_inconnu(self):
        """None → Inconnu"""
        assert GameService._get_relation_label(None) == "Inconnu"

    def test_hostile(self):
        """Niveaux bas → Hostile"""
        assert GameService._get_relation_label(0) == "Hostile"
        assert GameService._get_relation_label(1) == "Hostile"

    def test_neutre(self):
        """Niveaux 2-3 → Neutre"""
        assert GameService._get_relation_label(2) == "Neutre"
        assert GameService._get_relation_label(3) == "Neutre"

    def test_connaissance(self):
        """Niveaux 4-5 → Connaissance"""
        assert GameService._get_relation_label(4) == "Connaissance"
        assert GameService._get_relation_label(5) == "Connaissance"

    def test_ami(self):
        """Niveaux 6-7 → Ami"""
        assert GameService._get_relation_label(6) == "Ami"
        assert GameService._get_relation_label(7) == "Ami"

    def test_ami_proche(self):
        """Niveaux 8+ → Ami proche"""
        assert GameService._get_relation_label(8) == "Ami proche"
        assert GameService._get_relation_label(10) == "Ami proche"
        assert GameService._get_relation_label(100) == "Ami proche"

    def test_negative_values(self):
        """Valeurs négatives → Hostile"""
        assert GameService._get_relation_label(-1) == "Hostile"
        assert GameService._get_relation_label(-10) == "Hostile"


class TestGetPriority:
    """Tests pour _get_priority"""

    def test_with_deadline_always_haute(self):
        """Avec deadline → haute"""
        assert GameService._get_priority("task", 5) == "haute"
        assert GameService._get_priority("promise", 10) == "haute"
        assert GameService._get_priority("secret", 1) == "haute"

    def test_arc_without_deadline(self):
        """Arc sans deadline → haute"""
        assert GameService._get_priority("arc", None) == "haute"

    def test_secret_without_deadline(self):
        """Secret sans deadline → normale"""
        assert GameService._get_priority("secret", None) == "normale"

    def test_chekhov_gun_without_deadline(self):
        """Chekhov gun sans deadline → normale"""
        assert GameService._get_priority("chekhov_gun", None) == "normale"

    def test_other_types_without_deadline(self):
        """Autres types sans deadline → basse"""
        assert GameService._get_priority("task", None) == "basse"
        assert GameService._get_priority("promise", None) == "basse"
        assert GameService._get_priority("unknown", None) == "basse"
        assert GameService._get_priority("", None) == "basse"


class TestRelationLabelBoundaries:
    """Tests des valeurs limites pour _get_relation_label"""

    @pytest.mark.parametrize(
        "level,expected",
        [
            (0, "Hostile"),
            (1, "Hostile"),
            (2, "Neutre"),
            (3, "Neutre"),
            (4, "Connaissance"),
            (5, "Connaissance"),
            (6, "Ami"),
            (7, "Ami"),
            (8, "Ami proche"),
            (9, "Ami proche"),
        ],
    )
    def test_all_levels(self, level, expected):
        """Test paramétré de tous les niveaux"""
        assert GameService._get_relation_label(level) == expected
