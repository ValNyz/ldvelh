"""Per-model call rules (ModelProfile) applied by every LLM provider."""

from dataclasses import dataclass, fields


@dataclass(frozen=True)
class ModelProfile:
    """How a given model must be called.

    send_temperature: include `temperature` in requests (some models reject it).
    force_tool: force the single tool via tool_choice (Anthropic); else "auto".
    thinking: Anthropic "thinking" field, sent via extra_body.
    thinking_headroom: extra max_tokens for always-thinking models.
    """

    send_temperature: bool = True
    force_tool: bool = True
    thinking: dict | None = None
    thinking_headroom: int = 0

    @classmethod
    def from_dict(cls, data: dict | None) -> "ModelProfile":
        if not data:
            return DEFAULT_PROFILE
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}


DEFAULT_PROFILE = ModelProfile()
