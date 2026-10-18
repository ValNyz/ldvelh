"""Semantic keys of the facts the populator writes about the protagonist.

Keyed by role, not by the PC's name (#28). Migration 20261018000003_protagonist_ref renamed
the former name-based arrival and item-use keys of existing games.
"""

ARRIVAL_KEY_LIKE = "protagonist:arrival:%"  # SQL LIKE pattern of every arrival key


def arrival_key(part: str) -> str:
    """Key of one arrival fact: station, sensory, incident, mood, need."""
    return f"protagonist:arrival:{part}"


def use_key(object_ref: str) -> str:
    """Key of the fact "the protagonist uses <object>" (30-char object slug)."""
    return f"protagonist:use:{object_ref.lower().replace(' ', '_')[:30]}"
