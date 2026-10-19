"""Loose CI guard on the journal trigger overhead (#105): the measured figures go in the
log; the assertion only catches an order-of-magnitude regression. It bounds the real commit
path (`commit_turn`), the less noisy of the two measurements."""

import logging

import pytest

from tests.benchmark.journal_overhead import measure, measure_commit
from tests.test_game_and_populator import _setup_game_with_world

pytestmark = pytest.mark.integration

logger = logging.getLogger(__name__)


async def test_journal_trigger_overhead_is_bounded(client, test_user, test_pool):
    game_id, _, _ = await _setup_game_with_world(client, test_user, test_pool)

    micro = await measure(test_pool, game_id, rounds=50)
    commit = await measure_commit(test_pool, game_id, rounds=50)

    logger.info("journal overhead: micro=%s commit=%s", micro, commit)
    # The guard measures what it claims: the journaled commits wrote the journal, the
    # disabled ones did not.
    assert micro["micro_journal_bytes_per_round"] > 0
    assert commit["commit_journaled_changes"] > 0
    assert commit["commit_disabled_changes"] == 0
    assert commit["commit_overhead"] < 1.0
