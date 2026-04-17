-- migrate:up
-- Rename "personal_assistant" to "companion" in genre world_gen_examples
-- so the LLM generates the correct key name directly

UPDATE genres SET world_gen_example = replace(world_gen_example::text, '"personal_assistant"', '"companion"')::jsonb
WHERE world_gen_example::text LIKE '%personal_assistant%';

-- migrate:down
UPDATE genres SET world_gen_example = replace(world_gen_example::text, '"companion"', '"personal_assistant"')::jsonb
WHERE world_gen_example::text LIKE '%"companion"%';
