"""
LDVELH - Entity upsert guards (#87)

Extractors often list an entity that already exists in entities_created again, with
defaults for every field they do not repeat (NULL, '' or []). The ON CONFLICT branch of
an entity upsert must therefore only replace a stored value with a real one: a NULL, an
empty (or whitespace-only) string or an empty array keeps what is stored.
known_by_protagonist is never in an upsert's SET list: only explicit reveals
(entity_reveals, now_known) change it.
"""

# Column kinds; `None` = only NULL is blank (uuid, int, ...).
TEXT = "text"  # NULL, '' and whitespace-only are blank (a kept value is trimmed)
ARRAY = "array"  # NULL and '{}' are blank


def non_blank(value: str, kind: str | None) -> str:
    """SQL expression: `value`, or NULL when it is blank for its column kind."""
    if kind == TEXT:
        return f"NULLIF(BTRIM({value}), '')"
    if kind == ARRAY:
        return f"NULLIF({value}, '{{}}')"
    return value


def keep_unless_blank(table: str, column: str, kind: str | None = None) -> str:
    """SET item `column = new value, unless it is NULL or blank, else the stored one`."""
    return f"{column} = COALESCE({non_blank(f'EXCLUDED.{column}', kind)}, {table}.{column})"


def guarded_set(table: str, columns: dict[str, str | None]) -> str:
    """The DO UPDATE SET list of an entity upsert: every column guarded, then updated_at."""
    items = [keep_unless_blank(table, col, kind) for col, kind in columns.items()]
    return ",\n                ".join([*items, "updated_at = NOW()"])
