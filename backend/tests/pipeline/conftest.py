import pytest

from config import get_settings


@pytest.fixture
def log_prompts(monkeypatch):
    """LOG_PROMPTS=true for the test; the settings cache is cleared on setup and teardown."""
    monkeypatch.setenv("LOG_PROMPTS", "true")
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("LOG_PROMPTS")
    get_settings.cache_clear()
