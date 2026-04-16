-- migrate:up

-- Director plans table — one row per Director run, history preserved
CREATE TABLE director_plans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    game_id UUID NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    cycle INT NOT NULL,
    ig_time VARCHAR(10),
    tension_level INT NOT NULL DEFAULT 3 CHECK (tension_level BETWEEN 1 AND 5),
    narrator_guidance TEXT NOT NULL DEFAULT '',
    planned_events JSONB DEFAULT '[]',
    long_term_vision TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_director_plans_game_cycle ON director_plans(game_id, cycle DESC, ig_time DESC);

-- Game duration preference (short/medium/long)
ALTER TABLE games ADD COLUMN game_duration VARCHAR(10) DEFAULT 'medium';

-- Track when Director last ran (to compute elapsed IG time)
ALTER TABLE games ADD COLUMN last_director_time VARCHAR(10);

-- migrate:down
DROP TABLE IF EXISTS director_plans;
ALTER TABLE games DROP COLUMN IF EXISTS game_duration;
ALTER TABLE games DROP COLUMN IF EXISTS last_director_time;
