"""
Tests unitaires pour game_service.py
Focus sur les helpers statiques (logique pure)
+ Integration tests for CRUD operations
"""

import uuid

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


# =============================================================================
# INTEGRATION TESTS — require the ldvelh_test database
# =============================================================================


pytestmark_integration = pytest.mark.integration


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_and_list_games(test_pool, test_user):
    """Create 2 games for the same user, verify list returns 2."""
    service = GameService(test_pool)
    user_id = test_user["id"]

    game_id_1 = await service.create_game(user_id)
    game_id_2 = await service.create_game(user_id)

    assert game_id_1 != game_id_2

    games = await service.list_games(user_id)
    assert len(games) == 2
    ids = {g["id"] for g in games}
    assert str(game_id_1) in ids
    assert str(game_id_2) in ids


@pytest.mark.integration
@pytest.mark.asyncio
async def test_delete_game(test_pool, test_user):
    """Create a game, delete it, verify list returns 0."""
    service = GameService(test_pool)
    user_id = test_user["id"]

    game_id = await service.create_game(user_id)
    games_before = await service.list_games(user_id)
    assert len(games_before) == 1

    await service.delete_game(game_id)

    games_after = await service.list_games(user_id)
    assert len(games_after) == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_rename_game(test_pool, test_user):
    """Create a game, rename it, verify the name changed."""
    service = GameService(test_pool)
    user_id = test_user["id"]

    game_id = await service.create_game(user_id)

    await service.rename_game(game_id, "Mon aventure épique")

    games = await service.list_games(user_id)
    assert len(games) == 1
    assert games[0]["name"] == "Mon aventure épique"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_verify_ownership(test_pool, test_user):
    """Owner can access their game; a random UUID cannot."""
    from fastapi import HTTPException

    service = GameService(test_pool)
    user_id = test_user["id"]

    game_id = await service.create_game(user_id)

    # Owner access should succeed (no exception)
    await service.verify_ownership(game_id, user_id)

    # A random user should get a 403
    stranger_id = uuid.uuid4()
    with pytest.raises(HTTPException) as exc_info:
        await service.verify_ownership(game_id, stranger_id)
    assert exc_info.value.status_code == 403
