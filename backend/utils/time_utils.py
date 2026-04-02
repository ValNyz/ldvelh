"""
LDVELH - Time Utilities
Helpers for parsing and comparing in-game times (HHhMM format).
"""

import re


def parse_game_time(time_str: str) -> float | None:
    """Parse 'HHhMM' to hours as float. Returns None if unparsable."""
    if not time_str:
        return None
    m = re.match(r"^(\d{1,2})h(\d{2})$", time_str.strip())
    if not m:
        return None
    return int(m.group(1)) + int(m.group(2)) / 60.0


def game_hours_elapsed(from_time: str, to_time: str) -> float:
    """In-game hours between two times (same day, no wrap).

    Returns 0.0 if either time is unparsable or to_time <= from_time.
    """
    t_from = parse_game_time(from_time)
    t_to = parse_game_time(to_time)
    if t_from is None or t_to is None:
        return 0.0
    elapsed = t_to - t_from
    return max(0.0, elapsed)
