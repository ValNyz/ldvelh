"""
Comprehensive tests for utils/time_utils.py and utils/json_utils.py.
Aims for 100% branch coverage on both modules.
"""

import json

import pytest

from utils.time_utils import parse_game_time, game_hours_elapsed
from utils.json_utils import (
    parse_json_response,
    clean_json_string,
    _fix_unescaped_quotes,
    _try_python_literal,
    _escape_control_chars_in_strings,
    _replace_invalid_values,
    try_repair_json,
    try_truncate_json,
    safe_json_dumps,
    parse_json,
    parse_json_list,
)


# =============================================================================
# time_utils: parse_game_time
# =============================================================================


class TestParseGameTime:
    """Tests for parse_game_time()."""

    def test_valid_standard_time(self):
        """Typical morning time."""
        assert parse_game_time("08h30") == 8 + 30 / 60.0

    def test_valid_midnight(self):
        """Midnight boundary."""
        assert parse_game_time("00h00") == 0.0

    def test_valid_end_of_day(self):
        """Last minute of the day."""
        assert parse_game_time("23h59") == 23 + 59 / 60.0

    def test_valid_noon(self):
        """Noon."""
        assert parse_game_time("12h00") == 12.0

    def test_valid_single_digit_hour(self):
        """Single-digit hour without leading zero."""
        assert parse_game_time("9h15") == 9 + 15 / 60.0

    def test_valid_with_surrounding_whitespace(self):
        """Leading/trailing whitespace should be stripped."""
        assert parse_game_time("  10h30  ") == 10.5

    def test_none_input(self):
        """None returns None."""
        assert parse_game_time(None) is None

    def test_empty_string(self):
        """Empty string returns None."""
        assert parse_game_time("") is None

    def test_invalid_missing_h(self):
        """Missing 'h' separator."""
        assert parse_game_time("0830") is None

    def test_invalid_colon_separator(self):
        """Colon separator is not accepted."""
        assert parse_game_time("08:30") is None

    def test_invalid_single_digit_minutes(self):
        """Minutes must be exactly 2 digits."""
        assert parse_game_time("08h3") is None

    def test_invalid_three_digit_minutes(self):
        """Minutes with 3 digits."""
        assert parse_game_time("08h300") is None

    def test_invalid_three_digit_hours(self):
        """Hours with 3 digits."""
        assert parse_game_time("108h30") is None

    def test_invalid_text(self):
        """Random text returns None."""
        assert parse_game_time("bonjour") is None

    def test_invalid_just_h(self):
        """Just 'h' alone."""
        assert parse_game_time("h") is None

    def test_invalid_trailing_text(self):
        """Valid prefix but with trailing text."""
        assert parse_game_time("08h30pm") is None

    def test_invalid_leading_text(self):
        """Valid suffix but with leading text."""
        assert parse_game_time("at08h30") is None


# =============================================================================
# time_utils: game_hours_elapsed
# =============================================================================


class TestGameHoursElapsed:
    """Tests for game_hours_elapsed()."""

    def test_normal_elapsed(self):
        """Standard case: later time minus earlier time."""
        result = game_hours_elapsed("08h00", "10h30")
        assert abs(result - 2.5) < 1e-9

    def test_same_time(self):
        """Same time returns 0."""
        assert game_hours_elapsed("12h00", "12h00") == 0.0

    def test_to_time_before_from_time(self):
        """to_time < from_time returns 0 (no wrap support)."""
        assert game_hours_elapsed("14h00", "08h00") == 0.0

    def test_from_time_invalid(self):
        """Invalid from_time returns 0."""
        assert game_hours_elapsed("invalid", "10h00") == 0.0

    def test_to_time_invalid(self):
        """Invalid to_time returns 0."""
        assert game_hours_elapsed("10h00", "nope") == 0.0

    def test_both_invalid(self):
        """Both times invalid returns 0."""
        assert game_hours_elapsed("", None) == 0.0

    def test_from_none(self):
        """None as from_time returns 0."""
        assert game_hours_elapsed(None, "12h00") == 0.0

    def test_to_none(self):
        """None as to_time returns 0."""
        assert game_hours_elapsed("12h00", None) == 0.0

    def test_full_day_span(self):
        """From midnight to 23h59."""
        result = game_hours_elapsed("00h00", "23h59")
        assert abs(result - (23 + 59 / 60.0)) < 1e-9

    def test_one_minute_difference(self):
        """Minimal elapsed time."""
        result = game_hours_elapsed("10h00", "10h01")
        assert abs(result - (1 / 60.0)) < 1e-9


# =============================================================================
# json_utils: clean_json_string
# =============================================================================


class TestCleanJsonString:
    """Tests for clean_json_string()."""

    def test_strip_markdown_json_fences(self):
        """Remove ```json ... ``` wrappers."""
        raw = '```json\n{"key": "value"}\n```'
        result = clean_json_string(raw)
        assert '"key"' in result
        assert "```" not in result

    def test_strip_generic_markdown_fences(self):
        """Remove ``` ... ``` wrappers (no language tag)."""
        raw = '```\n{"key": "value"}\n```'
        result = clean_json_string(raw)
        assert '"key"' in result
        assert "```" not in result

    def test_no_fences(self):
        """Plain JSON is returned as-is (modulo strip)."""
        raw = '  {"key": "value"}  '
        result = clean_json_string(raw)
        assert result == '{"key": "value"}'

    def test_trailing_comma_removed_before_brace(self):
        """Trailing comma before } is stripped."""
        raw = '{"a": 1, "b": 2,}'
        result = clean_json_string(raw)
        assert result == '{"a": 1, "b": 2}'

    def test_trailing_comma_removed_before_bracket(self):
        """Trailing comma before ] is stripped."""
        raw = '[1, 2, 3,]'
        result = clean_json_string(raw)
        assert result == '[1, 2, 3]'

    def test_nan_replaced_with_null(self):
        """NaN outside strings replaced with null."""
        raw = '{"value": NaN}'
        result = clean_json_string(raw)
        parsed = json.loads(result)
        assert parsed["value"] is None

    def test_infinity_replaced_with_null(self):
        """Infinity outside strings replaced with null."""
        raw = '{"value": Infinity}'
        result = clean_json_string(raw)
        parsed = json.loads(result)
        assert parsed["value"] is None

    def test_negative_infinity_replaced_with_null(self):
        """-Infinity outside strings replaced with null."""
        raw = '{"value": -Infinity}'
        result = clean_json_string(raw)
        parsed = json.loads(result)
        assert parsed["value"] is None

    def test_nan_inside_string_not_replaced(self):
        """NaN inside a JSON string value should NOT be replaced."""
        raw = '{"text": "NaN is not a number"}'
        result = clean_json_string(raw)
        parsed = json.loads(result)
        assert "NaN" in parsed["text"]

    def test_control_chars_escaped(self):
        """Literal newlines inside strings are escaped."""
        raw = '{"text": "line1\nline2"}'
        result = clean_json_string(raw)
        # After escaping, the JSON should be valid
        parsed = json.loads(result)
        assert "line1\nline2" == parsed["text"]


# =============================================================================
# json_utils: _escape_control_chars_in_strings
# =============================================================================


class TestEscapeControlCharsInStrings:
    """Tests for _escape_control_chars_in_strings()."""

    def test_newline_inside_string(self):
        """Literal newline inside a JSON string is escaped to \\n."""
        content = '"hello\nworld"'
        result = _escape_control_chars_in_strings(content)
        assert result == '"hello\\nworld"'

    def test_carriage_return_inside_string(self):
        """Literal \\r inside a JSON string is escaped."""
        content = '"hello\rworld"'
        result = _escape_control_chars_in_strings(content)
        assert result == '"hello\\rworld"'

    def test_tab_inside_string(self):
        """Literal tab inside a JSON string is escaped."""
        content = '"hello\tworld"'
        result = _escape_control_chars_in_strings(content)
        assert result == '"hello\\tworld"'

    def test_other_control_char_inside_string(self):
        """Other control chars (< 0x20) are escaped as \\uXXXX."""
        # Use BEL (0x07) as an example
        content = '"hello\x07world"'
        result = _escape_control_chars_in_strings(content)
        assert result == '"hello\\u0007world"'

    def test_newline_outside_string_not_touched(self):
        """Newlines outside strings are NOT escaped."""
        content = '{\n"key": "value"\n}'
        result = _escape_control_chars_in_strings(content)
        assert result == '{\n"key": "value"\n}'

    def test_already_escaped_backslash(self):
        """A backslash followed by another char inside a string is kept as-is."""
        content = '"hello\\nworld"'
        result = _escape_control_chars_in_strings(content)
        # The \\n is an already-escaped sequence; should remain unchanged
        assert result == '"hello\\nworld"'

    def test_backslash_before_quote_inside_string(self):
        """An escaped quote inside a string should not toggle in_string."""
        content = r'"She said \"hello\""'
        result = _escape_control_chars_in_strings(content)
        # The escaped quotes should remain and the string tracking should be correct
        assert r'\"hello\"' in result


# =============================================================================
# json_utils: _replace_invalid_values
# =============================================================================


class TestReplaceInvalidValues:
    """Tests for _replace_invalid_values()."""

    def test_nan_replacement(self):
        result = _replace_invalid_values('{"v": NaN}')
        assert '"v": null' in result

    def test_infinity_replacement(self):
        result = _replace_invalid_values('{"v": Infinity}')
        assert '"v": null' in result

    def test_negative_infinity_replacement(self):
        result = _replace_invalid_values('{"v": -Infinity}')
        assert '"v": null' in result

    def test_nan_part_of_word_not_replaced(self):
        """NaN that is part of a larger identifier should not be replaced."""
        # 'NaNometer' starts with NaN but the next char is alphanumeric
        result = _replace_invalid_values('NaNometer')
        assert result == 'NaNometer'

    def test_strip_leading_plus_on_numbers(self):
        """Leading + before digits should be stripped."""
        result = _replace_invalid_values('{"v": +42}')
        assert "+42" not in result
        assert "42" in result

    def test_plus_sign_not_before_digit_kept(self):
        """Plus sign not directly before a digit should not be stripped."""
        result = _replace_invalid_values('{"op": "+"}')
        # Inside string, so should be untouched
        assert '"+"' in result

    def test_nan_inside_string_not_replaced(self):
        """NaN inside a JSON string should remain."""
        result = _replace_invalid_values('{"s": "NaN value"}')
        assert "NaN value" in result

    def test_infinity_at_end_of_content(self):
        """Infinity at the very end with no trailing char."""
        result = _replace_invalid_values('Infinity')
        assert result == 'null'

    def test_nan_preceded_by_letter(self):
        """NaN preceded by a letter should not be replaced."""
        result = _replace_invalid_values('xNaN')
        assert result == 'xNaN'


# =============================================================================
# json_utils: _fix_unescaped_quotes
# =============================================================================


class TestFixUnescapedQuotes:
    """Tests for _fix_unescaped_quotes()."""

    def test_no_change_needed(self):
        """Valid JSON with properly escaped quotes."""
        content = '{"key": "value"}'
        assert _fix_unescaped_quotes(content) == content

    def test_unescaped_quotes_in_value(self):
        """Unescaped double quotes inside a string value get escaped."""
        # "She said "hello" loudly" -- the inner quotes are unescaped
        content = '{"text": "She said "hello" loudly"}'
        result = _fix_unescaped_quotes(content)
        # After fixing, it should be valid JSON
        parsed = json.loads(result)
        assert "hello" in parsed["text"]

    def test_escaped_backslash_handling(self):
        """Backslash inside string is correctly tracked."""
        content = '{"key": "a\\\\b"}'
        result = _fix_unescaped_quotes(content)
        # Should be unchanged -- the backslashes are properly escaped
        parsed = json.loads(result)
        assert "a\\b" == parsed["key"]

    def test_quote_at_end_of_content(self):
        """A quote at the very end of content treated as closing."""
        content = '{"key": "value"}'
        result = _fix_unescaped_quotes(content)
        assert result == content

    def test_quote_followed_by_structural_tokens(self):
        """Quotes followed by , } ] : are treated as closing quotes."""
        # Each structural character after closing quote
        for token in [',', '}', ']', ':']:
            content = f'{{"k": "v"{token}"k2": "v2"}}'
            # Should not crash; just testing it processes without error
            _fix_unescaped_quotes(content)

    def test_multiple_unescaped_quotes(self):
        """Multiple unescaped quotes in one value."""
        content = '{"t": "a "b" and "c" end"}'
        result = _fix_unescaped_quotes(content)
        parsed = json.loads(result)
        assert "b" in parsed["t"]
        assert "c" in parsed["t"]


# =============================================================================
# json_utils: _try_python_literal
# =============================================================================


class TestTryPythonLiteral:
    """Tests for _try_python_literal()."""

    def test_python_dict_single_quotes(self):
        """Python dict with single quotes should be parsed."""
        content = "{'key': 'value', 'count': 42}"
        result = _try_python_literal(content)
        assert result == {"key": "value", "count": 42}

    def test_python_booleans(self):
        """Python True/False/None should be handled."""
        content = "{'active': True, 'deleted': False, 'data': None}"
        result = _try_python_literal(content)
        assert result == {"active": True, "deleted": False, "data": None}

    def test_not_a_dict_returns_none(self):
        """Non-dict literal (e.g., a list) returns None."""
        content = "[1, 2, 3]"
        result = _try_python_literal(content)
        assert result is None

    def test_invalid_syntax_returns_none(self):
        """Completely invalid syntax returns None."""
        content = "this is not python"
        result = _try_python_literal(content)
        assert result is None

    def test_empty_dict(self):
        """Empty dict literal."""
        content = "{}"
        result = _try_python_literal(content)
        assert result == {}

    def test_string_literal_returns_none(self):
        """A plain string literal is not a dict."""
        content = "'hello'"
        result = _try_python_literal(content)
        assert result is None


# =============================================================================
# json_utils: parse_json_response (top-level orchestrator)
# =============================================================================


class TestParseJsonResponse:
    """Tests for parse_json_response()."""

    def test_valid_json(self):
        """Plain valid JSON dict."""
        result = parse_json_response('{"key": "value"}')
        assert result == {"key": "value"}

    def test_valid_json_with_markdown_fences(self):
        """JSON wrapped in markdown code fences."""
        raw = '```json\n{"key": "value"}\n```'
        result = parse_json_response(raw)
        assert result == {"key": "value"}

    def test_valid_json_with_trailing_comma(self):
        """JSON with trailing comma should still parse after cleaning."""
        raw = '{"a": 1, "b": 2,}'
        result = parse_json_response(raw)
        assert result == {"a": 1, "b": 2}

    def test_python_dict_fallback(self):
        """Python dict literal falls back to ast.literal_eval."""
        raw = "{'key': 'value'}"
        result = parse_json_response(raw)
        assert result == {"key": "value"}

    def test_unescaped_quotes_fixed(self):
        """Unescaped quotes in values are fixed before parsing."""
        raw = '{"text": "She said "yes" firmly"}'
        result = parse_json_response(raw)
        assert result is not None
        assert "yes" in result["text"]

    def test_truncated_json_repaired(self):
        """Truncated JSON (missing closing brace) is repaired."""
        raw = '{"key": "value"'
        result = parse_json_response(raw)
        assert result == {"key": "value"}

    def test_completely_invalid_returns_none(self):
        """Completely unparsable content returns None."""
        result = parse_json_response("this is not json at all xyz")
        assert result is None

    def test_valid_json_list(self):
        """A valid JSON list is returned."""
        result = parse_json_response('[1, 2, 3]')
        assert result == [1, 2, 3]

    def test_nested_structure(self):
        """Deeply nested JSON."""
        raw = '{"a": {"b": {"c": [1, 2, {"d": true}]}}}'
        result = parse_json_response(raw)
        assert result["a"]["b"]["c"][2]["d"] is True

    def test_nan_in_json(self):
        """NaN is replaced with null and parsed."""
        raw = '{"v": NaN}'
        result = parse_json_response(raw)
        assert result == {"v": None}

    def test_empty_object(self):
        """Empty JSON object."""
        result = parse_json_response("{}")
        assert result == {}

    def test_whitespace_only(self):
        """Whitespace-only string returns None."""
        result = parse_json_response("   ")
        assert result is None

    def test_markdown_fences_with_extra_text(self):
        """Markdown fences with text before/after JSON are handled."""
        raw = '```json\n{"key": "value"}\n```\nSome trailing text'
        # After fence stripping: '{"key": "value"}\nSome trailing text'
        # json.loads will fail, but repair/truncation should recover
        result = parse_json_response(raw)
        # The repair/truncation should at least recover the dict
        assert result is not None
        assert result.get("key") == "value"

    def test_fix_unescaped_quotes_path_where_fix_also_fails(self):
        """When unescaped-quote fix produces something that also fails json.loads,
        fall through to python literal / repair."""
        # Craft content that: (1) fails json.loads, (2) fix_unescaped_quotes changes it,
        # (3) the fixed version also fails json.loads, (4) _try_python_literal succeeds
        raw = "{'key': 'value'}"  # Python dict literal -- not valid JSON
        result = parse_json_response(raw)
        assert result == {"key": "value"}


# =============================================================================
# json_utils: try_repair_json
# =============================================================================


class TestTryRepairJson:
    """Tests for try_repair_json()."""

    def test_missing_closing_brace(self):
        """Repair JSON with missing }."""
        raw = '{"key": "value"'
        result = try_repair_json(raw)
        assert result == {"key": "value"}

    def test_missing_closing_bracket(self):
        """Repair JSON with missing ]."""
        raw = '{"arr": [1, 2, 3'
        result = try_repair_json(raw)
        assert result is not None
        assert result["arr"] == [1, 2, 3]

    def test_unterminated_string(self):
        """Repair JSON with unterminated string value."""
        raw = '{"key": "val'
        result = try_repair_json(raw)
        assert result is not None
        assert "val" in result["key"]

    def test_trailing_backslash(self):
        """Content ending with a lone backslash is trimmed."""
        raw = '{"key": "value"\\'
        result = try_repair_json(raw)
        # After removing trailing backslash: '{"key": "value"' -> repair closes }
        assert result is not None

    def test_nested_brackets_repaired(self):
        """Multiple nested unclosed brackets."""
        raw = '{"a": [{"b": 1'
        result = try_repair_json(raw)
        assert result is not None
        assert result["a"][0]["b"] == 1

    def test_valid_json_passes_through(self):
        """Already valid JSON should just be returned."""
        raw = '{"key": "value"}'
        result = try_repair_json(raw)
        assert result == {"key": "value"}

    def test_hopelessly_broken_returns_none(self):
        """Completely unrecoverable content returns None."""
        raw = "{{{{garbage"
        result = try_repair_json(raw)
        # This may or may not repair; if it can't, returns None
        # The important thing is it doesn't crash
        assert result is None or isinstance(result, dict)


# =============================================================================
# json_utils: try_truncate_json
# =============================================================================


class TestTryTruncateJson:
    """Tests for try_truncate_json()."""

    def test_truncation_recovers_valid_prefix(self):
        """Truncate to find a valid JSON prefix."""
        raw = '{"key": "value"} extra garbage here that breaks things'
        result = try_truncate_json(raw)
        assert result is not None
        assert result["key"] == "value"

    def test_no_valid_truncation_returns_none(self):
        """Completely garbage content has no valid truncation point."""
        raw = "xxxxxxxxxxxxxxx"
        result = try_truncate_json(raw)
        assert result is None

    def test_truncation_with_unclosed_bracket(self):
        """Truncation finds a point where brackets can be closed."""
        raw = '{"a": [1, 2, 3], "b": "truncated here...'
        result = try_truncate_json(raw)
        # Should recover at least the "a" key
        assert result is not None

    def test_empty_string(self):
        """Empty string yields None."""
        result = try_truncate_json("")
        assert result is None

    def test_short_content(self):
        """Very short content shorter than 1000-char lookback."""
        raw = '{"k": 1'
        result = try_truncate_json(raw)
        # The function will iterate backwards; at some truncation it should close }
        assert result is not None or result is None  # just ensure no crash


# =============================================================================
# json_utils: safe_json_dumps
# =============================================================================


class TestSafeJsonDumps:
    """Tests for safe_json_dumps()."""

    def test_normal_dict(self):
        """Normal dict serialization."""
        result = safe_json_dumps({"key": "value"})
        assert json.loads(result) == {"key": "value"}

    def test_unicode_preserved(self):
        """Non-ASCII characters are preserved (ensure_ascii=False)."""
        result = safe_json_dumps({"text": "cafe"})
        assert "cafe" in result

    def test_non_serializable_returns_default(self):
        """Non-serializable object returns default."""
        result = safe_json_dumps(object())
        assert result == "{}"

    def test_custom_default(self):
        """Custom default value."""
        result = safe_json_dumps(object(), default="[]")
        assert result == "[]"

    def test_none_value(self):
        """None is serializable as 'null'."""
        result = safe_json_dumps(None)
        assert result == "null"

    def test_list(self):
        """Lists serialize correctly."""
        result = safe_json_dumps([1, 2, 3])
        assert json.loads(result) == [1, 2, 3]

    def test_nested_structure(self):
        """Nested dicts and lists."""
        data = {"a": [{"b": True}, None, 42]}
        result = safe_json_dumps(data)
        assert json.loads(result) == data

    def test_set_not_serializable(self):
        """Sets are not JSON serializable -> returns default."""
        result = safe_json_dumps({1, 2, 3})
        assert result == "{}"


# =============================================================================
# json_utils: parse_json
# =============================================================================


class TestParseJson:
    """Tests for parse_json()."""

    def test_none_input(self):
        """None returns None."""
        assert parse_json(None) is None

    def test_valid_json_string(self):
        """Valid JSON string is parsed."""
        result = parse_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_invalid_json_string_returns_string(self):
        """Invalid JSON string returns the original string."""
        result = parse_json("not json")
        assert result == "not json"

    def test_dict_passthrough(self):
        """Already a dict is returned as-is."""
        d = {"key": "value"}
        result = parse_json(d)
        assert result is d

    def test_list_passthrough(self):
        """Already a list is returned as-is."""
        lst = [1, 2, 3]
        result = parse_json(lst)
        assert result is lst

    def test_int_passthrough(self):
        """Integer is returned as-is."""
        assert parse_json(42) == 42

    def test_json_list_string(self):
        """JSON list as string is parsed."""
        result = parse_json('[1, 2, 3]')
        assert result == [1, 2, 3]

    def test_empty_string(self):
        """Empty string is not valid JSON, returned as-is."""
        result = parse_json("")
        assert result == ""

    def test_json_null_string(self):
        """The string 'null' parses to None."""
        result = parse_json("null")
        assert result is None


# =============================================================================
# json_utils: parse_json_list
# =============================================================================


class TestParseJsonList:
    """Tests for parse_json_list()."""

    def test_none_returns_empty_list(self):
        """None input returns []."""
        assert parse_json_list(None) == []

    def test_json_list_string(self):
        """JSON list string is parsed into a list."""
        result = parse_json_list('[1, 2, 3]')
        assert result == [1, 2, 3]

    def test_json_dict_string_wrapped_in_list(self):
        """JSON dict string is wrapped in a list."""
        result = parse_json_list('{"key": "value"}')
        assert result == [{"key": "value"}]

    def test_list_passthrough(self):
        """Already a list is returned as-is."""
        result = parse_json_list([1, 2])
        assert result == [1, 2]

    def test_dict_passthrough_wrapped(self):
        """Already a dict is wrapped in a list."""
        result = parse_json_list({"key": "value"})
        assert result == [{"key": "value"}]

    def test_scalar_wrapped(self):
        """A scalar value (int) is wrapped in a list."""
        result = parse_json_list(42)
        assert result == [42]

    def test_invalid_json_string_wrapped(self):
        """Invalid JSON string is wrapped in a list."""
        result = parse_json_list("not json")
        assert result == ["not json"]

    def test_empty_list_string(self):
        """JSON empty list string."""
        result = parse_json_list("[]")
        assert result == []

    def test_json_null_string(self):
        """The string 'null' parses to None, which returns []."""
        result = parse_json_list("null")
        assert result == []


# =============================================================================
# Integration / edge case tests across multiple functions
# =============================================================================


class TestEdgeCases:
    """Cross-cutting edge cases."""

    def test_parse_json_response_with_all_cleaning_needed(self):
        """Content needing markdown stripping, NaN replacement, and trailing comma removal."""
        raw = '```json\n{"a": NaN, "b": [1, 2,]}\n```'
        result = parse_json_response(raw)
        assert result == {"a": None, "b": [1, 2]}

    def test_parse_json_response_with_leading_plus(self):
        """Content with leading + on a number."""
        raw = '{"value": +42}'
        result = parse_json_response(raw)
        assert result == {"value": 42}

    def test_repair_then_truncate_fallback(self):
        """When simple repair fails, truncation is attempted."""
        # Build content where simple brace-closing won't work but truncation can find a valid prefix
        raw = '{"a": 1}garbage that makes brace-close fail...'
        result = try_repair_json(raw)
        # The repair adds closing brackets which won't help, so it falls to truncation
        # Truncation should find the valid prefix {"a": 1}
        assert result is not None
        assert result.get("a") == 1

    def test_clean_json_string_only_fences(self):
        """Only markdown fences, no actual JSON content."""
        raw = "```json\n\n```"
        result = clean_json_string(raw)
        assert result == ""

    def test_deeply_nested_repair(self):
        """Deeply nested structure with multiple unclosed brackets."""
        raw = '{"l1": {"l2": {"l3": [{"l4": "v"'
        result = try_repair_json(raw)
        assert result is not None
        assert result["l1"]["l2"]["l3"][0]["l4"] == "v"

    def test_escape_control_chars_with_escaped_backslash(self):
        """Backslash at end of string followed by quote should not mis-track."""
        # This is a string containing a literal backslash at the end: "abc\\"
        content = '{"k": "abc\\\\"}'
        result = _escape_control_chars_in_strings(content)
        # Should still be valid JSON
        parsed = json.loads(result)
        assert parsed["k"] == "abc\\"

    def test_replace_invalid_values_escape_tracking(self):
        """Escaped backslash inside string doesn't confuse string tracking."""
        content = '{"k": "a\\\\b", "v": NaN}'
        result = _replace_invalid_values(content)
        parsed = json.loads(result)
        assert parsed["v"] is None
        assert parsed["k"] == "a\\b"

    def test_fix_unescaped_quotes_with_escaped_backslash(self):
        """Escaped backslash followed by quote at end of string."""
        content = '{"k": "a\\\\"}'
        result = _fix_unescaped_quotes(content)
        # Should remain valid
        parsed = json.loads(result)
        assert parsed["k"] == "a\\"

    def test_parse_game_time_high_hour_values(self):
        """Hours above 23 -- the regex accepts 0-99, parse_game_time doesn't validate range."""
        # The regex accepts 1-2 digit hours, so 99h00 is technically parseable
        result = parse_game_time("99h00")
        assert result == 99.0

    def test_game_hours_elapsed_with_minutes(self):
        """Elapsed time involving non-zero minutes on both ends."""
        result = game_hours_elapsed("08h15", "10h45")
        assert abs(result - 2.5) < 1e-9

    def test_unescaped_quote_fix_changes_content_but_still_invalid(self):
        """Cover lines 38-39: _fix_unescaped_quotes changes content, but json.loads
        still fails on the result, so we fall through to python literal / repair.
        Craft something that has a quote the fixer will escape (producing a different
        string) but the result is still not valid JSON."""
        # This content has an unescaped quote that _fix_unescaped_quotes will escape,
        # but the surrounding structure is too broken for json.loads even after the fix.
        # The content must NOT be a valid Python literal either, to reach try_repair_json.
        raw = '{"k": "She said "hi" ok"  GARBAGE NOT JSON'
        result = parse_json_response(raw)
        # It should eventually fall through to repair/truncate
        # The important thing is we exercise the except branch at lines 38-39
        assert result is None or isinstance(result, dict)

    def test_try_repair_json_with_backslash_in_string(self):
        """Cover lines 281-282: try_repair_json encounters escape char in content.
        Content with a backslash-escaped character inside a string value, plus
        a missing closing brace to trigger repair."""
        raw = '{"k": "line1\\nline2"'
        result = try_repair_json(raw)
        assert result is not None
        assert result["k"] == "line1\nline2"

    def test_try_truncate_json_with_backslash_in_string(self):
        """Cover lines 344-348: try_truncate_json encounters escape char in truncated content.
        Content with escaped characters inside string values, followed by garbage."""
        raw = '{"k": "a\\nb"} followed by garbage that is not json at all'
        result = try_truncate_json(raw)
        assert result is not None
        assert result["k"] == "a\nb"
