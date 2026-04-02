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
