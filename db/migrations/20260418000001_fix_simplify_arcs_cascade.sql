-- migrate:up
-- Fix: previous migration failed because dependent objects blocked DROP COLUMN.
-- Re-attempt with CASCADE to remove views/triggers that reference these columns.

ALTER TABLE narrative_arcs DROP COLUMN IF EXISTS situation CASCADE;
ALTER TABLE narrative_arcs DROP COLUMN IF EXISTS desire CASCADE;
ALTER TABLE narrative_arcs DROP COLUMN IF EXISTS obstacle CASCADE;
ALTER TABLE narrative_arcs DROP COLUMN IF EXISTS potential_triggers CASCADE;
ALTER TABLE narrative_arcs DROP COLUMN IF EXISTS stakes CASCADE;
ALTER TABLE narrative_arcs DROP COLUMN IF EXISTS deadline_cycle CASCADE;
ALTER TABLE narrative_arcs DROP COLUMN IF EXISTS objective CASCADE;
ALTER TABLE narrative_arcs DROP COLUMN IF EXISTS steps CASCADE;
ALTER TABLE narrative_arcs DROP COLUMN IF EXISTS progress CASCADE;

-- Also drop the deadline index if it survived
DROP INDEX IF EXISTS idx_arcs_deadline;

-- migrate:down
-- Cannot restore CASCADE-dropped objects. Use baseline restore if needed.
