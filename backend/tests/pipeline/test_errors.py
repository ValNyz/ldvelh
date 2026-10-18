"""Failure -> one French TurnError, sent once on the sink (#45)."""

import logging

import pytest
from pydantic import BaseModel, ValidationError

from pipeline.errors import TurnError, finish_saved, report_error, to_turn_error
from pipeline.narration_stream import ProviderCallFailed
from schema.narration import NarrationInvalid, parse_narration


class _StatusError(Exception):
    def __init__(self, status_code: int):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


def _provider_failure(status_code: int) -> ProviderCallFailed:
    try:
        try:
            raise _StatusError(status_code)
        except _StatusError as e:
            raise ProviderCallFailed("anthropic") from e
    except ProviderCallFailed as failure:
        return failure


class _RecordingSink:
    def __init__(self):
        self.errors: list[dict] = []

    async def send_error(self, error, details=None, recoverable=False, code=None, ref=None):
        self.errors.append({"error": error, "details": details, "recoverable": recoverable,
                            "code": code, "ref": ref})


@pytest.mark.parametrize("status, code, recoverable", [
    (401, "provider_auth", False),
    (429, "provider_rate_limit", True),
    (500, "provider_error", True),
])
def test_provider_status_codes_map_to_codes(status, code, recoverable):
    err = to_turn_error(_provider_failure(status), "anthropic", "abc123")
    assert isinstance(err, TurnError)
    assert err.code == code
    assert err.recoverable is recoverable
    assert "anthropic" in err.message


def test_validation_error_is_narration_invalid():
    class _Model(BaseModel):
        x: int

    with pytest.raises(ValidationError) as info:
        _Model.model_validate({"x": "pas un nombre"})
    err = to_turn_error(info.value, "anthropic", "abc123")
    assert err.code == "narration_invalid"
    assert err.message == "La réponse du narrateur était inutilisable. Réessaie."
    assert err.recoverable is True


def test_narration_invalid_maps_to_french_error():
    err = to_turn_error(NarrationInvalid("narrative_text missing"), "anthropic", "abc123")
    assert err.code == "narration_invalid"
    assert err.message == "La réponse du narrateur était inutilisable. Réessaie."
    assert err.recoverable is True


def test_unknown_error_hides_its_text():
    exc = RuntimeError('insert or update on table "locations" violates foreign key')
    err = to_turn_error(exc, "anthropic", "abc123")
    assert err.code == "internal"
    assert "locations" not in err.message
    assert "réf. abc123" in err.message


def test_turn_error_passes_through():
    original = TurnError("custom", "Message perso.", recoverable=False)
    assert to_turn_error(original, "anthropic", "abc123") is original
    assert str(original) == "Message perso."


async def test_report_error_sends_once_without_details():
    sink = _RecordingSink()
    await report_error(sink, _provider_failure(500), provider_name="anthropic", ref="abc123")
    assert len(sink.errors) == 1
    sent = sink.errors[0]
    assert sent["details"] is None
    assert sent["code"] == "provider_error"
    assert sent["ref"] == "abc123"
    assert sent["recoverable"] is True


async def test_turn_error_with_cause_logs_the_cause(caplog):
    try:
        try:
            raise ValueError("bad world field")
        except ValueError as cause:
            raise TurnError("world_gen_failed", "Échec de génération du monde. Réessaie.") from cause
    except TurnError as e:
        error = e
    sink = _RecordingSink()
    with caplog.at_level("WARNING", logger="pipeline.errors"):
        await report_error(sink, error, provider_name="anthropic", ref="abc")
    record = next(r for r in caplog.records if "world_gen_failed" in r.getMessage())
    assert record.exc_info and record.exc_info[1] is error
    assert "bad world field" in caplog.text  # chained cause traceback is logged
    assert sink.errors[0]["error"] == "Échec de génération du monde. Réessaie."


async def test_turn_error_without_cause_logs_no_traceback(caplog):
    sink = _RecordingSink()
    with caplog.at_level("WARNING", logger="pipeline.errors"):
        await report_error(sink, TurnError("no_api_key", "x", recoverable=False),
                           provider_name="anthropic", ref="abc")
    record = next(r for r in caplog.records if "no_api_key" in r.getMessage())
    assert not record.exc_info


def _formatted(records) -> str:
    """What a handler writes for these records: message plus traceback."""
    formatter = logging.Formatter()
    return "\n".join(formatter.format(r) for r in records)


async def test_post_save_failure_is_logged_once_with_its_cause(caplog):
    async def failing_step():
        raise RuntimeError("db hiccup")

    sink = _RecordingSink()
    with caplog.at_level("DEBUG"):
        with pytest.raises(TurnError) as raised:
            await finish_saved(failing_step(), ref="abc")
        await report_error(sink, raised.value, provider_name="anthropic", ref="abc")
    logged = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(logged) == 1, [r.getMessage() for r in logged]
    assert logged[0].levelno == logging.ERROR
    assert "saved_display_failed" in logged[0].getMessage()
    assert "db hiccup" in _formatted(logged)
    assert sink.errors[0]["code"] == "saved_display_failed"


STORY = "Le dragon de verre murmure"


def _invalid_narration() -> NarrationInvalid:
    with pytest.raises(NarrationInvalid) as info:
        parse_narration({"narrative_text": STORY, "current_location": {"text": STORY}},
                        current_time="10:00", current_location="Quai")
    return info.value


async def test_validation_error_cause_never_leaks_story_text(caplog):
    invalid = _invalid_narration()
    assert isinstance(invalid.__cause__, ValidationError)
    assert STORY in str(invalid.__cause__)  # the leak this test guards against
    wrapped = TurnError("narration_invalid", "x")
    wrapped.__cause__ = invalid.__cause__
    sink = _RecordingSink()
    with caplog.at_level("INFO"):
        await report_error(sink, invalid, provider_name="anthropic", ref="abc")
        await report_error(sink, wrapped, provider_name="anthropic", ref="abc")
    logged = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(logged) == 2
    assert STORY not in _formatted(logged)
    assert "current_location: string_type" in _formatted(logged)  # the cause is still described
