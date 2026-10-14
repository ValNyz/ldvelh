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


# --- dbmate URL: sslmode=disable when the URL does not set one ---

from tests.conftest import _dbmate_url  # noqa: E402


def test_dbmate_url_adds_sslmode_when_no_query():
    assert _dbmate_url("postgresql://test:test@localhost:55432/ldvelh_test") == (
        "postgresql://test:test@localhost:55432/ldvelh_test?sslmode=disable"
    )


def test_dbmate_url_appends_sslmode_to_existing_params():
    assert _dbmate_url("postgresql://u:p@h:5432/x_test?connect_timeout=5") == (
        "postgresql://u:p@h:5432/x_test?connect_timeout=5&sslmode=disable"
    )


def test_dbmate_url_keeps_existing_sslmode():
    url = "postgresql://u:p@h:5432/x_test?sslmode=require"
    assert _dbmate_url(url) == url
