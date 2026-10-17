"""log_safe: exceptions are logged without the pydantic `input_value` (story text)."""

import logging

import pytest
from pydantic import BaseModel, ValidationError

from utils.log_safe import log_exception, safe_repr, validation_summary

STORY = "Le dragon de verre murmure"


class _Model(BaseModel):
    x: int


def _validation_error() -> ValidationError:
    with pytest.raises(ValidationError) as info:
        _Model.model_validate({"x": STORY})
    return info.value


def _chained() -> RuntimeError:
    try:
        try:
            raise _validation_error()
        except ValidationError as cause:
            raise RuntimeError("db hiccup") from cause
    except RuntimeError as e:
        return e


def test_summary_counts_errors_and_hides_input():
    summary = validation_summary(_validation_error())
    assert summary == "_Model: errors=1 (x: int_parsing)"
    assert STORY not in summary


def test_safe_repr_keeps_the_text_of_non_pydantic_exceptions():
    text = safe_repr(_chained())
    assert "RuntimeError: db hiccup" in text
    assert "errors=1 (x: int_parsing)" in text
    assert STORY not in text


def test_safe_repr_is_plain_repr_without_validation_error():
    assert safe_repr(RuntimeError("x")) == "RuntimeError('x')"


@pytest.mark.parametrize("exc_factory", [_validation_error, _chained])
def test_log_exception_never_leaks_at_warning_or_above(caplog, exc_factory):
    with caplog.at_level(logging.DEBUG):
        log_exception(logging.getLogger("t"), logging.ERROR, "failed", exc_factory())
    formatter = logging.Formatter()
    assert STORY not in "\n".join(formatter.format(r) for r in caplog.records)


def test_log_exception_traceback_without_validation_error(caplog):
    with caplog.at_level(logging.DEBUG):
        log_exception(logging.getLogger("t"), logging.ERROR, "failed", RuntimeError("boom"))
    assert caplog.records[0].exc_info[1].args == ("boom",)
