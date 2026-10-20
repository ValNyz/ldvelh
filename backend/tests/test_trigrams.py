"""utils/trigrams: pg_trgm's similarity in Python, checked against the database."""

import pytest

from utils.trigrams import (
    trigram_name_similarity,
    trigram_similarity,
    word_run_similarity,
)

PAIRS = [
    ("odran keswil", "keswil"),
    ("quai 9", "quai neuf"),
    ("cooperative", "cooperative agronomique"),
    ("pater", "pater ondrev"),
    ("serre numero quatre", "la serre"),
    ("bureau des residences", "residences"),
]


@pytest.mark.integration
@pytest.mark.parametrize("a,b", PAIRS)
async def test_parity_with_pg_trgm(test_pool, a, b):
    async with test_pool.acquire() as conn:
        similarity, strict = await conn.fetchrow(
            "SELECT similarity($1, $2), strict_word_similarity($1, $2)", a, b
        )
    assert trigram_similarity(a, b) == pytest.approx(similarity, abs=1e-6)
    assert word_run_similarity(a, b) == pytest.approx(strict, abs=1e-6)


def test_name_similarity_is_symmetric_and_finds_a_name_inside_another():
    assert trigram_name_similarity("keswil", "odran keswil") == 1
    assert trigram_name_similarity("odran keswil", "keswil") == 1
    assert trigram_name_similarity("keswil", "tassel") < 0.3
