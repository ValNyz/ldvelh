-- migrate:up

-- Per-message extraction replaces cycle-based checkpointing.
-- These columns are no longer used by any code.
ALTER TABLE games DROP COLUMN IF EXISTS extraction_checkpoints;
ALTER TABLE games DROP COLUMN IF EXISTS extracted_up_to_cycle;
ALTER TABLE messages DROP COLUMN IF EXISTS extracted;

-- migrate:down

ALTER TABLE games ADD COLUMN extraction_checkpoints JSONB DEFAULT '{}';
ALTER TABLE games ADD COLUMN extracted_up_to_cycle INTEGER DEFAULT 0;
ALTER TABLE messages ADD COLUMN extracted BOOLEAN DEFAULT false;
