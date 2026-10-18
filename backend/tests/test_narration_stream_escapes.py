"""Narration stream: JSON escapes decoded like json.loads, whatever the chunking (#90)."""

import json

import pytest

from pipeline.narration_stream import extract_narrative_from_partial

SAMPLES = [
    "Il était une fois à Genève, où l'été est très chaud.",
    "Smiley 😀 puis 🚀 fin.",
    'Elle dit : "Bonjour" puis \\ sortit.',
    "ligne 1\nligne 2\r\n\ttabulé / slash \b \f fin",
    "Mélange é😀\n\"q\"",
]


def _streamed(raw: str, cuts: tuple[int, ...]) -> str:
    """Concatenate the deltas the narration stream would send for these chunk boundaries."""
    sent = ""
    buffer = ""
    previous = 0
    for cut in (*cuts, len(raw)):
        buffer += raw[previous:cut]
        previous = cut
        displayable = extract_narrative_from_partial(buffer)
        if displayable and len(displayable) > len(sent):
            assert displayable.startswith(sent), "streamed text must only grow"
            sent = displayable
    return sent


@pytest.mark.parametrize("ensure_ascii", [True, False])
@pytest.mark.parametrize("text", SAMPLES)
def test_every_split_matches_json_loads(text, ensure_ascii):
    raw = json.dumps({"narrative_text": text, "x": 1}, ensure_ascii=ensure_ascii)
    expected = json.loads(raw)["narrative_text"].strip()
    for i in range(len(raw) + 1):
        assert _streamed(raw, (i,)) == expected, f"split at {i}"
    for i in range(0, len(raw), 3):  # two cuts: escape split in three pieces
        for j in range(i, min(i + 8, len(raw) + 1)):
            assert _streamed(raw, (i, j)) == expected, f"split at {i},{j}"


def _partial(body: str) -> str:
    return '{"narrative_text": "' + body


@pytest.mark.parametrize("body, expected", [
    ("a\\u00e9", "aé"),
    ("a\\u00e", "a"),
    ("a\\u00", "a"),
    ("a\\u", "a"),
    ("a\\", "a"),
    ("\\ud83d\\ude00", "😀"),
    ("x\\ud83d", "x"),            # high surrogate: wait for the low one
    ("x\\ud83d\\", "x"),
    ("x\\ud83d\\ude", "x"),
    ("x\\ud83d\\u0041", "x�A"),   # high surrogate not followed by a low one
    ("x\\ude00y", "x�y"),         # lone low surrogate
    ("x\\ud83dy", "x�y"),         # high surrogate followed by plain text
    ("x\\uZZZZy", "x\ufffdZZZZy"),   # invalid hex: only the escape is replaced
    ("\\/ \\b \\f", "/ \b \f"),
])
def test_unicode_escape_edge_cases(body, expected):
    assert extract_narrative_from_partial(_partial(body)) == (expected.strip() or None)


def test_lone_high_surrogate_at_end_of_string_is_replaced():
    assert extract_narrative_from_partial(_partial('x\\ud83d"}')) == "x�"


def test_result_is_always_encodable():
    for body in ("\\ud83d", "\\ude00", "\\ud83d\\ud83d", "\\uZZZZ"):
        text = extract_narrative_from_partial(_partial(body + '"}')) or ""
        text.encode("utf-8")
