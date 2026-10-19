"""LLM call log (#106): one row per billed call, and the account's cost summary read from it.

Accounting, not world state: written on its own connection right after each call, outside
any turn transaction, and never journaled.
"""

from uuid import UUID

_TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


async def insert_call(
    conn,
    *,
    turn_id: UUID | None,
    game_id: UUID | None,
    user_id: UUID | None,
    purpose: str,
    provider: str,
    model: str,
    usage: dict,
    cost_usd: float,
    cost_unknown: bool,
) -> None:
    """Log one call. `turn_id` is None outside a turn, `game_id` outside a game."""
    await conn.execute(
        """INSERT INTO llm_calls
           (turn_id, game_id, user_id, purpose, provider, model, usage, cost_usd, cost_unknown)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
        turn_id,
        game_id,
        user_id,
        purpose,
        provider,
        model,
        usage,
        cost_usd,
        cost_unknown,
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
