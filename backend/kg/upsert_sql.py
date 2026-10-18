"""
LDVELH - Entity upsert guards (#87)

Extractors often list an entity that already exists in entities_created again, with
defaults for every field they do not repeat (NULL, '' or []). The ON CONFLICT branch of
an entity upsert must therefore only replace a stored value with a real one: a NULL, an
empty string or an empty array keeps what is stored. known_by_protagonist is never in
an upsert's SET list: only explicit reveals (entity_reveals, now_known) change it.
"""

# Blank literal per column kind; `None` = only NULL is blank (uuid, int, ...).
TEXT = "''"
ARRAY = "'{}'"


def keep_unless_blank(table: str, column: str, blank: str | None = None) -> str:
    """SET item `column = new value, unless it is NULL or blank, else the stored one`."""
    new = f"EXCLUDED.{column}" if blank is None else f"NULLIF(EXCLUDED.{column}, {blank})"
    return f"{column} = COALESCE({new}, {table}.{column})"


def guarded_set(table: str, columns: dict[str, str | None]) -> str:
    """The DO UPDATE SET list of an entity upsert: every column guarded, then updated_at."""
    items = [keep_unless_blank(table, col, blank) for col, blank in columns.items()]
    return ",\n                ".join([*items, "updated_at = NOW()"])
