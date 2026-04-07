-- migrate:up

-- Extraction checkpoints: tracks per-type extraction progress
ALTER TABLE games ADD COLUMN extraction_checkpoints JSONB DEFAULT '{}';

-- Canonical name for object deduplication (snake_case key)
ALTER TABLE objects ADD COLUMN canonical_name VARCHAR(100);
CREATE UNIQUE INDEX idx_objects_canonical ON objects(game_id, canonical_name)
  WHERE canonical_name IS NOT NULL AND removed_cycle IS NULL;


-- migrate:down

DROP INDEX IF EXISTS idx_objects_canonical;
ALTER TABLE objects DROP COLUMN IF EXISTS canonical_name;
ALTER TABLE games DROP COLUMN IF EXISTS extraction_checkpoints;
