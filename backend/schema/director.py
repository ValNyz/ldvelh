"""
LDVELH - Director Schema
Models for the Director LLM narrative planning system.
"""

from pydantic import BaseModel, Field, field_validator


class PlannedEvent(BaseModel):
    """An event the Director plans for a future cycle."""

    cycle: int
    event: str = Field(..., max_length=300)
    location: str | None = None
    npcs_involved: list[str] = Field(default_factory=list)


class DirectorOutput(BaseModel):
    """Raw output from the Director LLM call."""

    tension_level: int = Field(default=3, ge=1, le=5)
    narrator_guidance: str = Field(
        default="",
        description="Tone, focus, NPC intentions, seeds to plant. Free text for the narrator.",
    )
    planned_events: list[PlannedEvent] = Field(
        default_factory=list,
        max_length=10,
        description="Events planned for upcoming cycles",
    )

    @field_validator("planned_events", mode="before")
    @classmethod
    def _normalize_events(cls, v):
        """LLMs sometimes generate strings instead of event objects."""
        if not isinstance(v, list):
            return v
        normalized = []
        for item in v:
            if isinstance(item, str):
                normalized.append({"cycle": 0, "event": item[:300]})
            else:
                normalized.append(item)
        return normalized
    long_term_vision: str = Field(
        default="",
        max_length=1000,
        description="Overall story direction, major reveals, pacing notes",
    )


class DirectorPlan(BaseModel):
    """A stored Director plan (DB row representation)."""

    cycle: int
    ig_time: str | None = None
    tension_level: int = 3
    narrator_guidance: str = ""
    planned_events: list[PlannedEvent] = Field(default_factory=list)
    long_term_vision: str = ""
