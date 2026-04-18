-- migrate:up
-- Simplify narrative_arcs: Director manages arc lifecycle now.
-- Remove scenario fields (handled by Director's guidance/planned_events).
-- Keep: title, description, domain (free text), intensity, owner, resolved, resolution.

ALTER TABLE narrative_arcs DROP COLUMN IF EXISTS situation CASCADE;
ALTER TABLE narrative_arcs DROP COLUMN IF EXISTS desire CASCADE;
ALTER TABLE narrative_arcs DROP COLUMN IF EXISTS obstacle CASCADE;
ALTER TABLE narrative_arcs DROP COLUMN IF EXISTS potential_triggers CASCADE;
ALTER TABLE narrative_arcs DROP COLUMN IF EXISTS stakes CASCADE;
ALTER TABLE narrative_arcs DROP COLUMN IF EXISTS deadline_cycle CASCADE;
ALTER TABLE narrative_arcs DROP COLUMN IF EXISTS objective CASCADE;
ALTER TABLE narrative_arcs DROP COLUMN IF EXISTS steps CASCADE;
ALTER TABLE narrative_arcs DROP COLUMN IF EXISTS progress CASCADE;

-- Drop the deadline index (column removed)
DROP INDEX IF EXISTS idx_arcs_deadline;

-- Remove domain constraint (was enforced by Pydantic enum, now free text)
-- Domain column is already VARCHAR(50), no change needed.

-- migrate:down
ALTER TABLE narrative_arcs ADD COLUMN IF NOT EXISTS situation TEXT;
ALTER TABLE narrative_arcs ADD COLUMN IF NOT EXISTS desire TEXT;
ALTER TABLE narrative_arcs ADD COLUMN IF NOT EXISTS obstacle TEXT;
ALTER TABLE narrative_arcs ADD COLUMN IF NOT EXISTS potential_triggers TEXT[];
ALTER TABLE narrative_arcs ADD COLUMN IF NOT EXISTS stakes TEXT;
ALTER TABLE narrative_arcs ADD COLUMN IF NOT EXISTS deadline_cycle INTEGER;
ALTER TABLE narrative_arcs ADD COLUMN IF NOT EXISTS objective TEXT;
ALTER TABLE narrative_arcs ADD COLUMN IF NOT EXISTS steps JSONB DEFAULT '[]';
ALTER TABLE narrative_arcs ADD COLUMN IF NOT EXISTS progress INTEGER DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_arcs_deadline ON narrative_arcs(game_id, deadline_cycle) WHERE resolved = false AND deadline_cycle IS NOT NULL;
