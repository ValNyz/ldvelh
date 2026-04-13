-- migrate:up

-- Narrative seeds: raw observable details planted by the GM.
-- Lifecycle: active -> archived (expired) or crystallized (became an arc)
CREATE TABLE narrative_seeds (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    game_id UUID NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    cycle INTEGER NOT NULL,
    text TEXT NOT NULL,
    location_id UUID REFERENCES locations(id),
    status VARCHAR(20) DEFAULT 'active',
    crystallized_arc_id UUID REFERENCES narrative_arcs(id),
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_seeds_game ON narrative_seeds(game_id);
CREATE INDEX idx_seeds_active ON narrative_seeds(game_id) WHERE status = 'active';

-- migrate:down

DROP TABLE IF EXISTS narrative_seeds;
