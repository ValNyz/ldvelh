"""Pure decoder for JSON string escapes met in a partially received stream (#90).

Matches json.loads for every complete escape. A lone surrogate becomes U+FFFD
(json.loads would keep it, but it cannot be encoded to UTF-8 for the client).
"""

from enum import Enum

REPLACEMENT_CHAR = "�"

_SIMPLE_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f",
                   '"': '"', "\\": "\\", "/": "/"}
_HEX = frozenset("0123456789abcdefABCDEF")


class Hex(Enum):
    OK = "ok"
    INCOMPLETE = "incomplete"  # fewer than 4 digits so far, all valid: wait for more input
    INVALID = "invalid"        # a non-hex character is already present


def _read_hex4(s: str, i: int) -> tuple[Hex, int]:
    """Four hex digits at s[i:i+4]: (status, value); the value is only meaningful for OK."""
    digits = s[i:i + 4]
    if not set(digits) <= _HEX:
        return Hex.INVALID, 0
    if len(digits) < 4:
        return Hex.INCOMPLETE, 0
    return Hex.OK, int(digits, 16)


def _decode_surrogate_pair(s: str, i: int, high: int) -> tuple[str, int] | None:
    """High surrogate already read, s[i:] follows: join it with a `\\uXXXX` low surrogate.

    None while the pair may still complete; otherwise a lone surrogate is U+FFFD.
    """
    rest = s[i:i + 6]
    if len(rest) < 6:
        if rest == "\\u"[:len(rest)] or (rest.startswith("\\u") and set(rest[2:]) <= _HEX):
            return None
        return REPLACEMENT_CHAR, i
    status, low = _read_hex4(s, i + 2) if rest.startswith("\\u") else (Hex.INVALID, 0)
    if status is Hex.OK and 0xDC00 <= low <= 0xDFFF:
        return chr(0x10000 + ((high - 0xD800) << 10) + (low - 0xDC00)), i + 6
    return REPLACEMENT_CHAR, i


def _decode_unicode_escape(s: str, i: int) -> tuple[str, int] | None:
    status, value = _read_hex4(s, i + 2)
    if status is Hex.INCOMPLETE:
        return None
    if status is Hex.INVALID:
        return REPLACEMENT_CHAR, i + 2  # the following characters stay literal
    end = i + 6
    if 0xD800 <= value <= 0xDBFF:
        return _decode_surrogate_pair(s, end, value)
    if 0xDC00 <= value <= 0xDFFF:
        return REPLACEMENT_CHAR, end
    return chr(value), end


def decode_json_escape(s: str, i: int) -> tuple[str, int] | None:
    """Decode the JSON escape whose backslash is at s[i].

    Returns (text, index after the escape), or None when the escape is cut off
    and the caller must wait for more input.
    """
    if i + 1 >= len(s):
        return None
    kind = s[i + 1]
    if kind == "u":
        return _decode_unicode_escape(s, i)
    return _SIMPLE_ESCAPES.get(kind, kind), i + 2
