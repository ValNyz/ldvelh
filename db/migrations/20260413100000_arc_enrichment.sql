-- migrate:up

-- Arc ownership: who drives this arc (protagonist, NPC, station/world)
ALTER TABLE narrative_arcs ADD COLUMN owner_id UUID REFERENCES entity_registry(id);

-- Arc objective: the goal, formulated as intention
ALTER TABLE narrative_arcs ADD COLUMN objective TEXT;

-- Arc steps: structured progression milestones
-- Format: [{title, status, description, risks[]}]
-- status: pending | active | completed | failed | skipped
ALTER TABLE narrative_arcs ADD COLUMN steps JSONB DEFAULT '[]';

CREATE INDEX idx_arcs_owner ON narrative_arcs(owner_id) WHERE owner_id IS NOT NULL;

-- migrate:down

DROP INDEX IF EXISTS idx_arcs_owner;
ALTER TABLE narrative_arcs DROP COLUMN IF EXISTS steps;
ALTER TABLE narrative_arcs DROP COLUMN IF EXISTS objective;
ALTER TABLE narrative_arcs DROP COLUMN IF EXISTS owner_id;
