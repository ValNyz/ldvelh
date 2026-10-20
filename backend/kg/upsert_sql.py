"""
LDVELH - Upsert guards (#87)

An extractor often lists again a row that already exists, with defaults for every field it
does not repeat (NULL, '' or []). An upsert's SET item must therefore only replace a stored
value with a real one: a NULL, an empty (or whitespace-only) string or an empty array keeps
what is stored. Used by narrative arcs and the narrative engine's traits; the entities'
own rule (the columns a re-listed entity may fill) lives in IdentityService (`refill`).
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
