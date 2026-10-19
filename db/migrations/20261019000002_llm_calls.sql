-- migrate:up
-- #106: one row per billed LLM call, linked to its turn (NULL outside a turn: world
-- generation, initial Director, form helpers). The account's cost summary is read from it,
-- so it survives a restart. Accounting, not world state: never journaled, and a rolled
-- back turn keeps its calls (they were paid).
CREATE TABLE public.llm_calls (
    id bigserial PRIMARY KEY,
    turn_id uuid REFERENCES public.turns(id) ON DELETE SET NULL,
    game_id uuid REFERENCES public.games(id) ON DELETE CASCADE,
    user_id uuid REFERENCES public.users(id) ON DELETE CASCADE,
    purpose text NOT NULL,
    provider text NOT NULL,
    model text NOT NULL,
    usage jsonb NOT NULL,
    cost_usd numeric(12, 6) NOT NULL,
    cost_unknown boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX llm_calls_user_created_idx ON public.llm_calls (user_id, created_at);
CREATE INDEX llm_calls_game_idx ON public.llm_calls (game_id);

-- migrate:down
DROP TABLE public.llm_calls;
