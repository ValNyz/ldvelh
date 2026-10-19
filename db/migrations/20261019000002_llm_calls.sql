-- migrate:up
-- #106: one row per billed LLM call, linked to its turn (NULL outside a turn: world
-- generation, initial Director, form helpers). The account's cost summary is read from it,
-- so it survives a restart. Accounting, not world state: never journaled, and a rolled
-- back turn or a deleted game keeps its calls (they were paid: SET NULL, not CASCADE).
CREATE TABLE public.llm_calls (
    id bigserial PRIMARY KEY,
    turn_id uuid REFERENCES public.turns(id) ON DELETE SET NULL,
    game_id uuid REFERENCES public.games(id) ON DELETE SET NULL,
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
-- Deleting a turn (rollback) sets its calls' turn_id to NULL: index the reference.
CREATE INDEX llm_calls_turn_idx ON public.llm_calls (turn_id) WHERE turn_id IS NOT NULL;

-- migrate:down
DROP INDEX public.llm_calls_turn_idx;
DROP TABLE public.llm_calls;
