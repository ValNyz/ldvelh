"""No language, genre or universe rule in the identity code: words live in the packs,
thresholds in IdentityConfig (spec §4.12, D33-D36, #152)."""

import ast
import re
from pathlib import Path

import pytest
import yaml

from packs.loader import PACKS_DIR, available_langs

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
# Pack keys that hold words; the others are settings or prose examples.
NON_LEXICAL_KEYS = frozenset(
    {
        "lang",
        "version",
        "apostrophes",
        "proper_name_uses_capitals",
        "min_distinctive_token_len",
        "prompt_examples",
    }
)
EXCLUDED_DIRS = ("packs/", "tests/", "evals/identity/lexicon/")
# Identity code: any literal equal to a pack word is a hard-coded rule.
IDENTITY_CODE = ("services/identity/", "prompts/identity_prompt.py")
# Justified exceptions as (path relative to backend/, folded literal) -> reason.
ALLOWED: dict[tuple[str, str], str] = {}
# English SQL keywords: words of the query language, not of a game's language. Only
# unquoted SQL is filtered with them: quoted literals are text, scanned word by word.
SQL_KEYWORDS = frozenset(
    {
        "as",
        "at",
        "by",
        "for",
        "from",
        "if",
        "in",
        "into",
        "is",
        "not",
        "of",
        "on",
        "or",
        "and",
        "to",
        "with",
        "no",
        "all",
        "any",
        # A PostgreSQL keyword, and the column of facts, events and relations.
        "type",
    }
)


def _fold(text: str) -> str:
    return text.replace("’", "'").casefold().strip()


def _words(value) -> set[str]:
    if isinstance(value, str):
        return {_fold(value)}
    if isinstance(value, list):
        return set().union(*map(_words, value)) if value else set()
    if isinstance(value, dict):
        return set().union(*map(_words, value.values())) if value else set()
    return set()


def _words_by_pack() -> dict[str, set[str]]:
    by_pack = {}
    for lang in available_langs():
        raw = yaml.safe_load(
            (PACKS_DIR / "lang" / f"{lang}.yaml").read_text(encoding="utf-8")
        )
        words = set()
        for key, value in raw.items():
            if key not in NON_LEXICAL_KEYS:
                words |= _words(value)
        by_pack[lang] = words - {""}
    return by_pack


def _pack_words() -> set[str]:
    return set().union(*_words_by_pack().values())


def _skipped_nodes(tree: ast.AST) -> set[int]:
    """Constants that are not words of a text: docstrings and f-string fragments (prose)."""
    skipped = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            skipped |= {id(v) for v in node.values}
        elif (
            isinstance(
                node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
            )
            and node.body
            and isinstance(node.body[0], ast.Expr)
        ):
            skipped.add(id(node.body[0].value))
    return skipped


def _field_names(tree: ast.AST) -> set[int]:
    """Single constants that name a field, not a text: dict keys, subscripts (`row["type"]`)
    and the arguments of `Literal[...]` (a subscript too). Their sets are still word lists
    to the collection check."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            names |= {id(k) for k in node.keys if k is not None}
        elif isinstance(node, ast.Subscript):
            index = node.slice
            elts = index.elts if isinstance(index, ast.Tuple) else [index]
            names |= {id(e) for e in elts}
    return names


def _is_word(node: ast.AST, words: set[str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        folded = _fold(node.value)
        return folded if folded in words else None
    return None


# A word between regex alternation delimiters: (?:le|la|les).
_ALTERNATIVE = re.compile(r"(?<=[|(:])([\w'’-]+)(?=[|)])")


def _word_list(items: list, packs: dict[str, set[str]], *, keyed: bool) -> set[str]:
    """Pack words of `items` when they form a word list: two distinct words of one pack. A
    dict's key or value set must also be at least half pack words: a record such as
    `{"type": …, "ms": …}` or a large vocabulary map with a few chance collisions is not a
    word list, `{"monsieur": 1, "madame": 2}` is."""
    texts = {
        _fold(i.value)
        for i in items
        if isinstance(i, ast.Constant) and isinstance(i.value, str)
    }
    hits = set()
    for words in packs.values():
        found = texts & words
        if len(found) >= 2 and (not keyed or 2 * len(found) >= len(texts)):
            hits |= found
    return hits


def _python_hits(
    path: Path, rel: str, words: set[str] | dict[str, set[str]]
) -> set[str]:
    """Hits of a module: in identity code every literal equal to a pack word (docstrings,
    f-string fragments and single field names aside); everywhere a word list (`_word_list`)
    in a list, tuple (`Literal[...]` arguments included), set, dict key set or dict value
    set, or a regex alternation of two pack words."""
    packs = words if isinstance(words, dict) else {"pack": words}
    every_word = set().union(*packs.values())
    tree = ast.parse(path.read_text(encoding="utf-8"))
    strict = rel.startswith(IDENTITY_CODE)
    skipped = _skipped_nodes(tree) | _field_names(tree)
    hits = set()
    for node in ast.walk(tree):
        if strict and id(node) not in skipped and (word := _is_word(node, every_word)):
            hits.add(word)
        elif isinstance(node, ast.Dict):
            hits |= _word_list([k for k in node.keys if k], packs, keyed=True)
            hits |= _word_list(node.values, packs, keyed=True)
        elif isinstance(node, ast.List | ast.Tuple | ast.Set):
            hits |= _word_list(node.elts, packs, keyed=False)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            alternatives = {_fold(a) for a in _ALTERNATIVE.findall(node.value)}
            for pack_words in packs.values():
                if len(alternatives & pack_words) >= 2:
                    hits |= alternatives & pack_words
    return {w for w in hits if (rel, w) not in ALLOWED}


def _python_files():
    for path in sorted(BACKEND.rglob("*.py")):
        rel = path.relative_to(BACKEND).as_posix()
        if not rel.startswith(EXCLUDED_DIRS):
            yield path, rel


def _identity_sql_files() -> list[Path]:
    migrations = REPO / "db" / "migrations"
    return sorted(
        {*migrations.glob("*entity_identity*.sql"), *migrations.glob("*identity*.sql")}
    )


# The P5b replay guard every side-effect trigger opens with (test_world_changes_undo): its
# 'on' is the value of a setting, not a word of a game's language.
_REPLAY_GUARD = re.compile(r"current_setting\('ldvelh\.replay', true\) = 'on'")


def _sql_without_comments(sql: str) -> str:
    """`sql` without its comments and replay guards: the text the scans read."""
    return _REPLAY_GUARD.sub(" ", re.sub(r"--[^\n]*", "", sql))


_SQL_QUOTED = re.compile(r"'((?:[^']|'')*)'")
_WORD = re.compile(r"\w+(?:['-]\w+)*'?")


def _sql_literal_words(sql: str) -> set[str]:
    """Every word inside the quoted literals of `sql` (a regex or a default text included)."""
    literals = _SQL_QUOTED.findall(_sql_without_comments(sql))
    return {w for q in literals for w in _WORD.findall(_fold(q.replace("''", "'")))}


def test_no_language_lexicon_in_code():
    words = _pack_words()
    by_pack = _words_by_pack()
    found = {
        f"{rel}: {sorted(hits)}"
        for path, rel in _python_files()
        if (hits := _python_hits(path, rel, by_pack))
    }
    for path in _identity_sql_files():
        if hits := _sql_literal_words(path.read_text(encoding="utf-8")) & words:
            found.add(f"{path.name}: {sorted(hits)}")
    assert found == set()


def test_the_literal_scan_catches_a_word_list_and_a_pattern(tmp_path):
    words = {"le", "la", "les"}
    module = tmp_path / "m.py"
    module.write_text(
        'ARTICLES = ("le", "la")\nPATTERN = r"^(?:le|la|les)\\s"\n'
        'KIND = {"le": 1, "la": 2}\nSINGLE = "la"\n',
        encoding="utf-8",
    )
    assert _python_hits(module, "pipeline/m.py", words) == {"le", "la", "les"}
    assert _python_hits(module, "services/identity/m.py", words) == {"le", "la", "les"}
    module.write_text('SINGLE = "la"\n', encoding="utf-8")
    assert _python_hits(module, "pipeline/m.py", words) == set()
    assert _python_hits(module, "services/identity/m.py", words) == {"la"}


def test_the_strict_scan_lets_field_names_through(tmp_path):
    words = {"type", "client", "le", "la", "les", "monsieur", "madame"}
    module = tmp_path / "m.py"
    module.write_text(
        'SCHEMA = {"type": "object"}\nKIND = row["type"]\nKind = Literal["type"]\n'
        'PAIR = table["type", "id"]\n',
        encoding="utf-8",
    )
    assert _python_hits(module, "services/identity/m.py", words) == set()
    module.write_text(
        'SINGLE = "type"\nSCHEMA = {"kind": "client"}\n', encoding="utf-8"
    )
    assert _python_hits(module, "services/identity/m.py", words) == {"type", "client"}


@pytest.mark.parametrize("rel", ["services/identity/m.py", "pipeline/m.py"])
def test_keyed_word_lists_are_caught(tmp_path, rel):
    words = {"le", "la", "les", "monsieur", "madame"}
    module = tmp_path / "m.py"
    module.write_text(
        'Article = Literal["le", "la", "les"]\nTITLES = {"monsieur": 1, "madame": 2}\n',
        encoding="utf-8",
    )
    assert _python_hits(module, rel, words) == words


def test_the_scan_catches_a_negative_answer_list(tmp_path):
    """The narrator parser's former word list is caught by construction: its words are
    `negative_answers` of the packs."""
    words = _pack_words()
    assert {"non", "aucune", "no"} <= words
    module = tmp_path / "m.py"
    module.write_text(
        'WORDS = frozenset({"", "null", "false", "none", "aucune", "non", "no"})\n',
        encoding="utf-8",
    )
    assert {"aucune", "non"} <= _python_hits(
        module, "schema/narration.py", _words_by_pack()
    )


def test_sql_literal_words_are_scanned_inside_the_literal():
    words = {"no", "inconnu"}
    sql = "SELECT regexp_replace(x, 'no|numero', ''), COALESCE(d, 'Inconnu(e)') -- no"
    assert _sql_literal_words(sql) & words == {"no", "inconnu"}


_SQL_FUNCTION = re.compile(
    r"CREATE (?:OR REPLACE )?FUNCTION\s+(?:\w+\.)?(\w+).*?AS\s+\$(\w*)\$(.*?)\$\2\$",
    re.DOTALL | re.IGNORECASE,
)


def test_sql_identity_functions_contain_no_pack_word():
    """Every function body of every identity migration: unquoted tokens and literals."""
    words = _pack_words()
    found, scanned = {}, set()
    for path in _identity_sql_files():
        sql = _sql_without_comments(path.read_text(encoding="utf-8"))
        bodies = [(m.group(1), m.group(3)) for m in _SQL_FUNCTION.finditer(sql)]
        scanned |= {name for name, _ in bodies}
        for name, body in bodies:
            unquoted = _SQL_QUOTED.sub(" ", body)
            tokens = set(_WORD.findall(unquoted.casefold())) - SQL_KEYWORDS
            if hits := (tokens | _sql_literal_words(body)) & words:
                found[f"{path.name}: {name}"] = sorted(hits)
    assert {
        "ldvelh_unaccent",
        "ldvelh_norm",
        "ldvelh_norm_for_game",
        "identity_label",
    } <= scanned
    assert found == {}


def _numbers(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        f"{path.name}:{node.lineno}: {node.value!r}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and type(node.value) in (int, float)
        and node.value not in (0, 1)
    ]


def test_identity_config_has_no_duplicate_literal_in_candidates_or_decision():
    """Thresholds and bounds come from IdentityConfig: no number other than 0 and 1 in the
    identity service (candidates.py and decision.py included once they exist)."""
    code = sorted((BACKEND / "services" / "identity").glob("*.py"))
    assert code
    assert [n for path in code for n in _numbers(path)] == []


# --- candidate blocking (#154): thresholds from IdentityConfig, words from the pack ---

_BLOCKING_SQL = ("_BLOCKING_ALIASES", "NAME_ALIAS_KINDS", "CANDIDATES_TRGM_SQL")
_SQL_NUMBER = re.compile(r"(?<![\w$.])\d+(?:\.\d+)?(?![\w.])")


def _blocking_sql_texts() -> list[str]:
    """String constants of the blocking queries of repos/entities.py: the module constants
    they share and the bodies of the `candidates_*`/`candidate_*` functions."""
    tree = ast.parse((BACKEND / "repos" / "entities.py").read_text(encoding="utf-8"))
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name.startswith(
            ("candidates_", "candidate_", "alias_max_words", "norm_for_game")
        ):
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id in _BLOCKING_SQL for t in node.targets
        ):
            nodes.append(node)
        elif isinstance(node, ast.ClassDef) and node.name == "ContextSource":
            nodes.append(node)
    skipped = {
        id(n.body[0].value)
        for n in nodes
        if isinstance(n, ast.AsyncFunctionDef | ast.ClassDef)
        and isinstance(n.body[0], ast.Expr)
    }
    return [
        c.value
        for n in nodes
        for c in ast.walk(n)
        if isinstance(c, ast.Constant)
        and isinstance(c.value, str)
        and id(c) not in skipped
    ]


def test_blocking_sql_has_no_threshold_literal_nor_pack_word():
    texts = _blocking_sql_texts()
    assert any("word_similarity" in t for t in texts)
    assert any("levenshtein_less_equal" in t for t in texts)
    assert "mentioned" in texts  # the context source names are scanned
    numbers = sorted(
        {n for t in texts for n in _SQL_NUMBER.findall(t) if float(n) not in (0, 1)}
    )
    assert numbers == []
    words = _pack_words()
    found = set()
    for text in texts:
        unquoted = _SQL_QUOTED.sub(" ", text)
        tokens = set(_WORD.findall(unquoted.casefold())) - SQL_KEYWORDS
        found |= (tokens | _sql_literal_words(text)) & words
    assert found == set()


async def _ondrev_game(test_pool, test_user, monkeypatch, s_word: str):
    from config import IdentityConfig
    from domain.identity import NewEntitySpec, SceneContext
    from repos import entities
    from services.identity.service import IdentityService

    monkeypatch.setenv("IDENTITY_S_WORD", s_word)
    config = IdentityConfig()
    async with test_pool.acquire() as conn:
        game = await conn.fetchval(
            "INSERT INTO games (user_id, language) VALUES ($1, 'fr') RETURNING id",
            test_user["id"],
        )
        service = IdentityService(game, lang="fr", config=config)
        ondrev = await service.create_entity(
            conn,
            NewEntitySpec("character", "Pater Ondrev Kasso", "proper_name"),
            turn_id=None,
            source="world_gen",
        )
        protagonist = await entities.insert_domain_row(
            conn, game, "protagonist", {"name": "Rafe"}, label_suffix=None
        )
    scene = SceneContext(None, [], [], [], [], [], protagonist, None)
    return service, scene, ondrev


async def _sources(
    test_pool, service, scene, entity_id, text, lexicon=None
) -> set[str]:
    from services.identity import candidates

    async with test_pool.acquire() as conn:
        found = await candidates.block(
            conn,
            service.game_id,
            text,
            scene,
            config=service.config,
            normalizer=service.normalizer,
            lexicon=lexicon or service.lexicon,
        )
    return next((c.sources for c in found.ranked() if c.entity_id == entity_id), set())


@pytest.mark.integration
async def test_thresholds_come_from_config(test_pool, test_user, monkeypatch):
    """IDENTITY_S_WORD changes what pg_trgm finds; the token generator does not read it."""
    from services.identity import candidates

    fuzzy, named = "Ondrav Kaso referme le registre.", "Ondrev referme le registre."
    loose = await _ondrev_game(test_pool, test_user, monkeypatch, "0.3")
    strict = await _ondrev_game(test_pool, test_user, monkeypatch, "0.99")
    assert loose[0].config.s_word == 0.3 and strict[0].config.s_word == 0.99
    assert candidates.TRGM in await _sources(test_pool, *loose, fuzzy)
    assert candidates.TRGM not in await _sources(test_pool, *strict, fuzzy)
    assert candidates.TOKENS in await _sources(test_pool, *strict, named)


@pytest.mark.integration
async def test_stop_words_and_titles_come_from_the_pack(
    test_pool, test_user, monkeypatch
):
    """A pack whose stop words hold the name: no candidate by shared words any more."""
    from packs.loader import load_genre, load_lang
    from services.identity import candidates
    from services.identity.lexicon import Lexicon

    service, scene, ondrev = await _ondrev_game(
        test_pool, test_user, monkeypatch, "0.99"
    )
    text = "Ondrev referme le registre."
    assert candidates.TOKENS in await _sources(test_pool, service, scene, ondrev, text)
    lang = load_lang("fr")
    stub = Lexicon(
        lang.model_copy(update={"stop_words": [*lang.stop_words, "ondrev"]}),
        load_genre(None),
    )
    found = await _sources(test_pool, service, scene, ondrev, text, stub)
    assert candidates.TOKENS not in found
    titled = Lexicon(
        lang.model_copy(update={"titles": [*lang.titles, "ondrev"]}), load_genre(None)
    )
    assert candidates.TOKENS not in await _sources(
        test_pool, service, scene, ondrev, text, titled
    )


def _fr_only_entries() -> set[str]:
    """Phrases of the French pack (multi-word cues and the examples): single words may
    also be English ones the generic rules use."""
    fr = yaml.safe_load((PACKS_DIR / "lang" / "fr.yaml").read_text(encoding="utf-8"))
    cues = [*fr["reveal_cues"], *fr["source_cues"], *fr["descriptor_heads"]]
    entries = {c for c in cues if len(c.split()) > 1}
    for examples in fr["prompt_examples"].values():
        entries |= {e["input"] for e in examples} | {e["output"] for e in examples}
    return entries


@pytest.mark.integration
async def test_pipeline_is_parametrizable_with_the_en_stub_pack(test_pool, test_user):
    """A game in English on the witness pack: normalisation, aliases, prepass, blocking
    and the identity prompt all follow the English pack, nothing depends on `fr`."""
    import json

    from config import get_identity_config
    from domain.identity import NewEntitySpec, SceneContext, TurnRef
    from llm.session import LLMSession
    from repos import entities, messages
    from services.identity.service import IdentityService
    from tests.characterization.scripted_llm import ScriptedLLMProvider

    # The capitalised form is linked; the lower-case one is a doubt for the model.
    text = "Reyes walks to the Mill. Later the mill creaks."
    async with test_pool.acquire() as conn:
        game = await conn.fetchval(
            "INSERT INTO games (user_id, language) VALUES ($1, 'en') RETURNING id",
            test_user["id"],
        )
        service = IdentityService(game, lang="en", config=get_identity_config())
        protagonist = await entities.insert_domain_row(
            conn, game, "protagonist", {"name": "Ash"}, label_suffix=None
        )
        made = {}
        for entity_type, label in (
            ("location", "The Old Mill"),
            ("character", "Captain Reyes"),
            ("organization", "the Guild"),
        ):
            made[label] = await service.create_entity(
                conn,
                NewEntitySpec(entity_type, label, "proper_name"),
                turn_id=None,
                source="world_gen",
            )
        norm = await conn.fetchval("SELECT ldvelh_norm_for_game($1, $2)", game, "The Old Mill")
        reyes_aliases = {
            a.alias for a in await entities.list_aliases(conn, game, made["Captain Reyes"])
        }
        conversation = await messages.insert_conversation(conn, game, 1)
        message = await messages.insert_message(conn, game, conversation, "assistant", text, 1)

        provider = ScriptedLLMProvider({"identity": json.dumps({"mentions": []})})
        prompts = []
        answer = provider.complete_with_tools

        async def spy(*args, **kwargs):
            prompts.extend(str(value) for value in [*args, *kwargs.values()])
            return await answer(*args, **kwargs)

        provider.complete_with_tools = spy
        scene = SceneContext(
            location_id=None,
            present_ids=[],
            recent_message_ids=[],
            reveal_refs=[],
            planned_npc_handles=[],
            open_disclosure_ids=[],
            protagonist_id=protagonist,
            companion_id=None,
        )
        session = LLMSession.from_provider(provider)
        candidates = await service.block(conn, text, scene)
        decided = await service.decide(conn, session, text, scene, candidates)
        resolution = await service.apply_resolution(
            conn, TurnRef(None, message, 1), text, scene, decided
        )
    assert norm == "old mill"
    assert "Reyes" in reyes_aliases
    assert [(m.surface, m.entity_id, m.decision) for m in resolution.mentions] == [
        ("Reyes", made["Captain Reyes"], "deterministic"),
        ("Mill", made["The Old Mill"], "deterministic"),  # the article left out (M9)
    ]
    assert made["The Old Mill"] in {c.entity_id for c in decided.candidates.ranked()}
    assert not decided.decisions.fallback
    rendered = " ".join(prompts)
    assert not {e for e in _fr_only_entries() if e in rendered}
    english = yaml.safe_load((PACKS_DIR / "lang" / "en.yaml").read_text(encoding="utf-8"))
    assert english["prompt_examples"]["identity"][0]["input"] in rendered
    to_check = rendered[rendered.index("## TO CHECK") :]
    assert '"the mill"' in to_check[:120]
