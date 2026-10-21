"""Prompt of the resolver v2's listwise identity decision (spec §4.5.2-§4.5.3, §4.12).

The rules are generic: no word of a language and no name of a universe here. The lists
the rules cite (pronouns, phrases that introduce a name, in-world sources of a name) and
the examples come from the game's packs (`prompt_examples.identity` of the genre, else of
the language). The model writes no label and no confidence: it picks a handle among the
candidates' (an enum of the schema) or abstains with UNSURE.
"""

from __future__ import annotations

import json
from typing import Protocol

from config import IdentityConfig, get_identity_config
from domain.identity import (
    ALIAS_KINDS,
    DECISIONS,
    NEW_ENTITY_TYPES,
    NEW_KINDS,
    Candidate,
)
from packs.loader import Example, LangPack

# Neutral markers: the head of every identity prompt, and of the strong model's.
IDENTITY_PROMPT_MARKER = "## IDENTITY RESOLUTION"
IDENTITY_STRONG_MARKER = "## SECOND OPINION"
# Tool (or JSON schema) name of the decision output.
DECISION_TOOL = "identity_decisions"
SEPARATOR = " · "
PROTAGONIST = "PROTAGONIST"
# Marks of a name the protagonist does not know (on a card).
UNKNOWN = " (unknown to the PC)"
NAME_UNKNOWN = " (name unknown to the PC)"


class IdentityLexicon(Protocol):
    """What the prompt reads of a game's lexicon (services.identity.lexicon.Lexicon)."""

    lang: LangPack
    prompt_examples: list[Example]


def format_handle(handle: int) -> str:
    return f"E{handle}"


def _listed(entries: list[str]) -> str:
    """Pack entries as the prompt cites them: in pack order, once each, quoted."""
    return ", ".join(f'"{e}"' for e in dict.fromkeys(entries))


def _examples(examples: list[Example]) -> str:
    return "\n".join(f"- {e.input}\n  -> {e.output}" for e in examples)


_RULES = """\
You link the mentions of a story passage to the entities of a game.

Find every mention in the NARRATION that names or describes a character, a location, an \
organization or an object, and decide for each one. A common noun phrase that designates \
one of the CANDIDATES (a description, a possessive phrase, a shortened reference) is a \
mention too: decide it.
- MATCH: it names or describes a candidate; give that candidate's handle.
- ALIAS: it names a candidate by a name its card does not list yet (a short form, a \
nickname, a true name); give the handle and the alias_kind. A description that designates \
a candidate is MATCH, not ALIAS.
- NEW: a really new entity the story follows: a person, a place, a group, or an object \
that is named, given, taken or used; give new_type and new_kind (proper_name or \
descriptor). Never write a label: the code takes the surface.
- UNSURE: two or more candidates fit, or a candidate and a new entity are equally likely. \
An abstention is better than a guess between them; when no candidate fits, decide NEW \
or SKIP instead.
- SKIP: nothing to link.

Rules:
1. A title alone is not enough when several candidates hold it.
2. The same name held by cards of different kinds (a place and an organization, say) \
names distinct entities, unless the text says they are one. Pick the kind the sentence \
calls for: what one goes to, enters, leaves or is in is a place; what decides, sends, \
employs, pays or rules is an organization or a person; what speaks, looks or moves by \
itself is a person; what is held, given, opened, carried or used is an object. When the \
sentence allows several kinds, UNSURE.
3. Two people who talk to each other in the scene are distinct: list each one in the \
other's talks_to.
4. A self-introduction by an entity whose name is still unknown and who is present in the \
scene is ALIAS with alias_kind true_name for that entity. Phrases that introduce a name: \
{reveal_cues}.
5. A name read in the world ({source_cues}) reveals the name of what bears it, like a \
self-introduction.
6. Pronouns ({pronouns}), body parts and anonymous crowds are SKIP.
7. Objects only seen, never named nor handled, are SKIP; so are the belongings and \
clothes a person merely has or wears in passing.
8. The PROTAGONIST card is the player's character, the COMPANION card its companion: \
MATCH them, never create them.
9. The mentions under ALREADY RESOLVED are decided: do not repeat them.
10. A part of an entity (the handle of a tool, the lid of a box) is not that entity: SKIP.
11. Members of a group, counted or described one by one, are not the group itself: SKIP \
unless the text names the group.
12. Each mention under TO CHECK is written like a name of the candidate given after it, \
but as a common noun: decide it (MATCH that candidate or another, NEW, or SKIP); never \
leave one out.
13. A possessive or a description that ties an object to another person does not \
designate an object carried by the PROTAGONIST, unless the text says it changed hands: \
NEW or SKIP by the rules above.

For each mention give: surface (the exact words of the mention in the narration, \
not the words before it), before (the \
{before_words} words just before it), decision, handle (a handle of the \
CANDIDATES, or null), alias_kind, new_type, new_kind, evidence (at most \
{evidence_max_words} words) and talks_to (the surfaces it speaks with), when relevant."""

_STRONG = """\
A first pass left the mentions under MENTIONS TO DECIDE undecided or risky (a revealed \
name, a link that would merge two entities). Decide only the mentions listed there; leave \
out every other mention."""


def build_identity_system_prompt(
    lexicon: IdentityLexicon,
    *,
    strong: bool = False,
    config: IdentityConfig | None = None,
) -> str:
    """The system prompt of the identity decision; `strong`: the escalation's, which
    decides only the mentions it lists. `config`: the limits it states (the caller's,
    else the global one)."""
    config = config or get_identity_config()
    pack = lexicon.lang
    pronouns = [
        *pack.pronouns.personal,
        *pack.pronouns.demonstrative,
        *pack.pronouns.indefinite,
    ]
    rules = _RULES.format(
        reveal_cues=_listed(pack.reveal_cues),
        source_cues=_listed(pack.source_cues),
        pronouns=_listed(pronouns),
        before_words=config.before_words,
        evidence_max_words=config.evidence_max_words,
    )
    parts = [IDENTITY_PROMPT_MARKER]
    if strong:
        parts += [IDENTITY_STRONG_MARKER, _STRONG]
    parts.append(rules)
    if lexicon.prompt_examples:
        parts.append("Examples:\n" + _examples(lexicon.prompt_examples))
    return "\n\n".join(parts)


def _section(title: str, lines: list[str]) -> str:
    return f"## {title}\n" + ("\n".join(lines) if lines else "(none)")


def build_identity_user_prompt(
    text: str,
    cards: list[str],
    resolved: list[str],
    scene_lines: list[str],
    *,
    mentions: list[str] | None = None,
    to_check: list[str] | None = None,
    schema: dict | None = None,
) -> str:
    """The user message: the narration, the candidate cards, the mentions the prepass
    already resolved and the scene. `mentions`: the only ones to decide (escalation);
    `schema`: the output schema, written out when the provider cannot enforce it."""
    sections = [
        _section("NARRATION", [text]),
        _section("CANDIDATES", cards),
        _section("ALREADY RESOLVED", resolved),
        _section("SCENE", scene_lines),
    ]
    if to_check:
        sections.append(_section("TO CHECK", to_check))
    if mentions is not None:
        sections.append(_section("MENTIONS TO DECIDE", mentions))
    if schema is not None:
        sections.append(
            _section(
                "OUTPUT",
                ["One JSON object matching this schema:", json.dumps(schema)],
            )
        )
    return "\n\n".join(sections)


def _quoted(text: str) -> str:
    return f'"{text}"'


def render_card(
    c: Candidate,
    *,
    protagonist: bool,
    companion: bool,
    homonyms: list[tuple[str, str]] | tuple = (),
) -> str:
    """One candidate as the model sees it (§4.5.2): handle, type, role, the label the
    player may read, a true name the protagonist does not know yet, the other aliases
    and descriptors, occupation, usual place, last turn seen and one line of
    description."""
    parts = [format_handle(c.handle), c.entity_type]
    if protagonist:
        parts.append(PROTAGONIST)
    if companion:
        parts.append("COMPANION")
    if c.carried:
        parts.append(f"carried by the {PROTAGONIST}")
    label = _quoted(c.label)
    shown = {c.label.casefold()}
    unknown_label = next(
        (a for a in c.aliases if a.alias.casefold() in shown and not a.known), None
    )
    if unknown_label is not None:  # the label itself is a name the PC does not know
        label += NAME_UNKNOWN if unknown_label.kind == "true_name" else UNKNOWN
    names, descriptors = [], []
    for a in c.aliases:
        if a.alias.casefold() in shown:
            continue
        shown.add(a.alias.casefold())
        if a.kind == "true_name" and not a.known:
            label += f" (name {_quoted(a.alias)} unknown to the PC)"
            continue
        form = _quoted(a.alias) + ("" if a.known else UNKNOWN)
        (descriptors if a.kind == "descriptor" else names).append(form)
    parts.append(label)
    if names:
        parts.append("aliases: " + ", ".join(names))
    if descriptors:
        parts.append("descriptors: " + ", ".join(descriptors))
    if c.occupation:
        parts.append(f"occupation: {c.occupation}")
    if c.usual_location:
        parts.append(f"usual place: {c.usual_location}")
    if c.last_seen_turn is not None:
        parts.append(f"seen at turn {c.last_seen_turn}")
    if c.description_line:
        parts.append(c.description_line)
    if homonyms:
        others = ", ".join(f"{handle} ({kind})" for handle, kind in homonyms)
        parts.append(f"same name as {others}: tell them apart by kind")
    return SEPARATOR.join(parts)


def _optional(values: tuple[str, ...]) -> dict:
    return {"type": ["string", "null"], "enum": [*values, None]}


def decision_schema(
    handles: list[str], *, config: IdentityConfig | None = None
) -> dict:
    """JSON schema of the decision output: `handle` can only be one of `handles` (or
    null), so the model cannot invent an id; no confidence field (UNSURE abstains)."""
    config = config or get_identity_config()
    item = {
        "type": "object",
        "properties": {
            "surface": {
                "type": "string",
                "description": "the mention, exactly as the narration writes it",
            },
            "before": {
                "type": "string",
                "description": f"the {config.before_words} words just before it",
            },
            "decision": {"type": "string", "enum": list(DECISIONS)},
            "handle": _optional(tuple(handles)),
            "alias_kind": _optional(ALIAS_KINDS),
            "new_type": _optional(NEW_ENTITY_TYPES),
            "new_kind": _optional(NEW_KINDS),
            "evidence": {
                "type": "string",
                "description": f"at most {config.evidence_max_words} words",
            },
            "talks_to": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["surface", "before", "decision", "handle", "evidence"],
    }
    return {
        "type": "object",
        "properties": {"mentions": {"type": "array", "items": item}},
        "required": ["mentions"],
    }
