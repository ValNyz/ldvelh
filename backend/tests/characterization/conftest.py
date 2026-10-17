"""Characterization tests: deterministic dice for every scenario (shared fixtures in tests/plugins/chat.py)."""

import pytest


@pytest.fixture(autouse=True)
def _seeded_random(seeded_random):
    """Every characterization scenario rolls the same dice."""
