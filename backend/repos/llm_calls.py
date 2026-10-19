"""LLM call log (#106): one row per billed call, and the account's cost summary read from it.

Accounting, not world state: written once per phase (llm/call_log.py) on its own
connection, outside any turn transaction, and never journaled.
"""

from uuid import UUID

_ROW_FIELDS = (
    "turn_id",
    "game_id",
    "user_id",
    "purpose",
    "provider",
    "model",
    "usage",
    "cost_usd",
    "cost_unknown",
    "created_at",
)
_TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


async def insert_calls(conn, rows: list[dict]) -> None:
    """Log the calls of one phase in one insert, in their order. Each row: turn_id (None
    outside a turn), game_id (None outside a game), user_id, purpose, provider, model,
    usage (dict), cost_usd, cost_unknown, created_at (the call's time). A turn (rollback)
    or a game deleted before the insert is stored as NULL, as their ON DELETE SET NULL
    would have done; a deletion racing the statement raises ForeignKeyViolationError
    (the caller retries)."""
    if not rows:
        return
    await conn.execute(
        """INSERT INTO llm_calls
           (turn_id, game_id, user_id, purpose, provider, model, usage, cost_usd,
            cost_unknown, created_at)
        SELECT CASE WHEN EXISTS (SELECT 1 FROM turns WHERE id = r.turn_id)
                    THEN r.turn_id END,
               CASE WHEN EXISTS (SELECT 1 FROM games WHERE id = r.game_id)
                    THEN r.game_id END,
               r.user_id, r.purpose, r.provider, r.model, r.usage, r.cost_usd,
               r.cost_unknown, r.created_at
        FROM unnest($1::uuid[], $2::uuid[], $3::uuid[], $4::text[], $5::text[], $6::text[],
                    $7::jsonb[], $8::numeric[], $9::boolean[], $10::timestamptz[])
             WITH ORDINALITY
             AS r(turn_id, game_id, user_id, purpose, provider, model, usage, cost_usd,
                  cost_unknown, created_at, n)
        ORDER BY r.n""",  # ids follow the call order
        *([row[key] for row in rows] for key in _ROW_FIELDS),
    )


async def user_summary(conn, user_id: UUID) -> dict:
    """All-time totals of the user's calls, per purpose then model, costs in USD (6 decimals):
    {"purposes": {purpose: {"models": {model: {<token fields>, "calls", "cost_usd"}},
    "cost_usd", "calls"}}, "total_cost_usd"}."""
    rows = await conn.fetch(
        """SELECT purpose, model,
                  sum((usage ->> 'input_tokens')::bigint) AS input_tokens,
                  sum((usage ->> 'output_tokens')::bigint) AS output_tokens,
                  sum((usage ->> 'cache_creation_input_tokens')::bigint)
                      AS cache_creation_input_tokens,
                  sum((usage ->> 'cache_read_input_tokens')::bigint) AS cache_read_input_tokens,
                  count(*) AS calls, sum(cost_usd) AS cost_usd
           FROM llm_calls WHERE user_id = $1
           GROUP BY purpose, model
           ORDER BY min(id)""",
        user_id,
    )
    purposes: dict[str, dict] = {}
    total = 0.0
    for r in rows:
        cost = float(r["cost_usd"])  # numeric comes back as Decimal
        total += cost
        entry = purposes.setdefault(
            r["purpose"], {"models": {}, "cost_usd": 0.0, "calls": 0}
        )
        entry["models"][r["model"]] = {
            **{field: int(r[field] or 0) for field in _TOKEN_FIELDS},
            "calls": r["calls"],
            "cost_usd": round(cost, 6),
        }
        entry["cost_usd"] = round(entry["cost_usd"] + cost, 6)
        entry["calls"] += r["calls"]
    return {"purposes": purposes, "total_cost_usd": round(total, 6)}
