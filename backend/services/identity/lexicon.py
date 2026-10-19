"""Words of a game: its language pack plus the identity section of its genre pack (§4.12).

Every word set holds pack entries in `Normalizer.key` form, so that normalised tokens and
heads compare with them directly.
"""

from __future__ import annotations

from functools import lru_cache

from packs.loader import Example, GenrePack, LangPack, load_genre, load_lang
from services.identity.normalize import Normalizer


class Lexicon:
    def __init__(self, lang: LangPack, genre: GenrePack):
        self.lang = lang
        self.genre = genre
        key = Normalizer(lang).key

        def keys(*lists: list[str]) -> frozenset[str]:
            return frozenset(key(w) for words in lists for w in words) - {""}

        pronouns = lang.pronouns
        self.titles = keys(lang.titles, genre.identity.titles_extra)
        self.stop_words = keys(lang.stop_words)
        self.pronouns_flat = keys(
            pronouns.personal, pronouns.demonstrative, pronouns.indefinite
        )
        self.descriptor_heads = keys(lang.descriptor_heads)
        self.reveal_cues = keys(lang.reveal_cues)
        self.source_cues = keys(lang.source_cues)
        self.min_distinctive_token_len = lang.min_distinctive_token_len
        self.prompt_examples: list[Example] = (
            genre.identity.prompt_examples.get("identity")
            or lang.prompt_examples.identity
        )


@lru_cache
def for_game(lang: str, genre: str | None) -> Lexicon:
    """The lexicon of a game's language and genre (neutral genre when it has no pack)."""
    return Lexicon(load_lang(lang), load_genre(genre))
