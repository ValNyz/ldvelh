-- migrate:up

-- Entity span annotations for coreference resolution and tooltips.
-- Format: [[char_start, char_end, canonical_name, entity_type], ...]
ALTER TABLE messages ADD COLUMN narrator_context JSONB;

-- migrate:down

ALTER TABLE messages DROP COLUMN IF EXISTS narrator_context;
