"""Unit tests for the fail-vs-skip decision when the test DB is unavailable (no DB needed)."""

import pytest
from _pytest.outcomes import Failed, Skipped

from tests.conftest import _db_unavailable


def test_skips_by_default(monkeypatch):
    monkeypatch.delenv("REQUIRE_TEST_DB", raising=False)
    with pytest.raises(Skipped, match="boom"):
        _db_unavailable("boom")


def test_skips_when_flag_not_one(monkeypatch):
    monkeypatch.setenv("REQUIRE_TEST_DB", "0")
    with pytest.raises(Skipped):
        _db_unavailable("boom")


def test_fails_when_required(monkeypatch):
    monkeypatch.setenv("REQUIRE_TEST_DB", "1")
    with pytest.raises(Failed, match="boom"):
        _db_unavailable("boom")
