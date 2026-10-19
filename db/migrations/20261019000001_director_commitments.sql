-- migrate:up
-- #107: commitments the Director makes (secrets, planned events, clocks, agendas). Schema
-- only for now; it sits under the turn journal like every other world table.
CREATE TABLE public.director_commitments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    game_id uuid NOT NULL REFERENCES public.games(id) ON DELETE CASCADE,
    turn_id uuid REFERENCES public.turns(id) ON DELETE SET NULL,
    kind text NOT NULL CHECK (kind IN ('secret', 'planned_event', 'clock', 'agenda')),
    text text NOT NULL,
    status text NOT NULL DEFAULT 'open',
    due_cycle integer,
    related_entities uuid[] NOT NULL DEFAULT '{}',
    progress integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX director_commitments_game_status_idx
    ON public.director_commitments (game_id, status);
SELECT public.ldvelh_journal('director_commitments');

-- migrate:down
DROP TABLE public.director_commitments;
