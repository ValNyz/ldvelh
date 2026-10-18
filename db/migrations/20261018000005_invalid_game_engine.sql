-- migrate:up
-- #91: POST /games used to store any engine string; EngineType("foo") then crashed every
-- load of the game. Existing rows with an unknown engine become 'none' (the code also
-- tolerates them at read time: schema.engine.coerce_engine).
UPDATE games SET engine = 'none' WHERE engine NOT IN ('none', 'narrative', 'fate_core', 'd6');

-- migrate:down
-- No-op: the rewritten values were invalid and are not recoverable.
SELECT 1;
