"""Loose CI guard on the journal trigger overhead (#105): the measured figure goes in the
log; the assertion only catches an order-of-magnitude regression."""

import logging

import pytest

from tests.benchmark.journal_overhead import measure
from tests.test_game_and_populator import _setup_game_with_world

pytestmark = pytest.mark.integration

logger = logging.getLogger(__name__)


async def test_journal_trigger_overhead_is_bounded(client, test_user, test_pool):
    game_id, _, _ = await _setup_game_with_world(client, test_user, test_pool)

    result = await measure(test_pool, game_id, rounds=30)

    logger.info("journal overhead: %s", result)
    assert result["journal_bytes_per_round"] > 0
    assert result["overhead"] < 1.0
