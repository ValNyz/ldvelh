"""Narrator time and date are normalised at the schema boundary (#86)."""

import logging

import pytest

from schema.narration import DayTransition, EventHint, TimeProgression


@pytest.mark.parametrize("raw, expected", [
    ("09h05", "09h05"), ("9h05", "09h05"), ("9h5", "09h05"), ("09:05", "09h05"),
    ("21H30", "21h30"), (" 21h30 ", "21h30"), ("0h00", "00h00"), ("23h59", "23h59"),
    ("9:5", "09h05"), ("9 h 05", "09h05"),
])
def test_accepted_time_formats_are_normalised(raw, expected):
    assert TimeProgression(new_time=raw).new_time == expected


@pytest.mark.parametrize("raw", [
    "vers 10h", "24h00", "10h60", "25h10", "10h", "h30", "", "10h300", "100h00",
    "10h15 environ", "midi", "minuit", "midi ", "9h60", "٩h٠٥", None, 1015, ["10h15"],
])
def test_rejected_time_formats_become_none(raw):
    assert TimeProgression(new_time=raw).new_time is None


def test_missing_time_is_none():
    assert TimeProgression().new_time is None


def test_rejected_time_warns_without_the_story_value(caplog):
    with caplog.at_level(logging.WARNING):
        TimeProgression(new_time="vers 10h")
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings
    assert all("vers 10h" not in r.getMessage() for r in warnings)


def test_event_hint_planned_time_is_normalised():
    assert EventHint(title="x", planned_time="9h5").planned_time == "09h05"
    assert EventHint(title="x", planned_time="ce soir").planned_time is None


def test_long_new_date_is_truncated_not_fatal():
    date = DayTransition(new_date="Jeudi " + "très long " * 20).new_date
    assert len(date) <= 50


def test_short_new_date_is_kept():
    assert DayTransition(new_date="Jeudi 16 Mars 2847").new_date == "Jeudi 16 Mars 2847"


@pytest.mark.parametrize("model, kwargs", [
    ("EventScheduledExtraction", dict(event_type="meeting", title="x", planned_cycle=2)),
    ("NarrativeExtraction", {}),
    ("FactData", dict(cycle=1, fact_type="event", description="x", semantic_key="a:b:c")),
    ("EventScheduled", dict(event_type="meeting", title="x", planned_cycle=2)),
])
def test_extractor_side_times_are_normalised_or_none(model, kwargs):
    from schema import extraction, narrative
    cls = getattr(extraction, model, None) or getattr(narrative, model)
    assert cls(time="vers 10h", **kwargs).time is None
    assert cls(time="9h5", **kwargs).time == "09h05"
