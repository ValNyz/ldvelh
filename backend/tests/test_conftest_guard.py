"""Guard: fixtures must never truncate a non-test database (#58)."""

import pytest

from tests.conftest import assert_safe_test_db_url


def test_accepts_test_database():
    assert_safe_test_db_url("postgresql://u:p@localhost:5432/ldvelh_test")
    assert_safe_test_db_url("postgresql://u:p@db:5432/ldvelh_test?sslmode=disable")


@pytest.mark.parametrize("url", [
    "postgresql://u:p@localhost:5432/ldvelh",
    "postgresql://u:p@prod-host:5432/postgres",
    "postgresql://u:p@localhost:5432/ldvelh_test_backup_real",
])
def test_rejects_non_test_database(url):
    with pytest.raises(RuntimeError, match="_test"):
        assert_safe_test_db_url(url)
