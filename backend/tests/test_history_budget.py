"""Narrator history is bounded; cache_control only for providers that support it (#21)."""

from services.game_service import GameService


def _pairs(n, size=40):
    out = []
    for i in range(n):
        out.append({"role": "user", "content": f"u{i} " + "x" * size})
        out.append({"role": "assistant", "content": f"a{i} " + "y" * size})
    return out


def test_trim_history_caps_message_count_and_starts_on_user():
    kept = GameService._trim_history(_pairs(100))
    assert len(kept) <= GameService.HISTORY_MAX_MESSAGES
    assert kept[0]["role"] == "user" and kept[-1]["content"].startswith("a99")


def test_trim_history_respects_token_budget():
    kept = GameService._trim_history(_pairs(20, size=8_000))  # ~2k tokens per message
    assert sum(len(m["content"]) // 4 for m in kept) <= GameService.HISTORY_TOKEN_BUDGET
    assert kept and kept[0]["role"] == "user"


def test_trim_history_keeps_short_history_untouched():
    history = _pairs(3)
    assert GameService._trim_history(history) == history


def test_no_cache_control_without_capability():
    messages = GameService._apply_cache_breakpoints(_pairs(3), enabled=False, prev_cycle_idx=1)
    assert all(isinstance(m["content"], str) for m in messages)


def test_anthropic_marks_last_history_message_and_previous_cycle_end():
    messages = GameService._apply_cache_breakpoints(_pairs(3), enabled=True, prev_cycle_idx=1)
    marked = [i for i, m in enumerate(messages) if isinstance(m["content"], list)]
    assert marked == [1, 5]
    assert messages[5]["content"][0]["cache_control"] == {"type": "ephemeral"}
