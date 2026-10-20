-- migrate:up
-- Catalog roles of the resolver v2's identity decision (#154, spec §4.5.5): the small
-- model decides every turn, the strong one only the escalated mentions. A provider with
-- no holder falls back to its narration model (llm/session.py).
UPDATE public.llm_models
   SET roles = array_append(roles, 'identity'), updated_at = now()
 WHERE provider = 'anthropic' AND model_id = 'claude-haiku-5-5'
   AND NOT ('identity' = ANY(roles));
UPDATE public.llm_models
   SET roles = array_append(roles, 'identity_strong'), updated_at = now()
 WHERE provider = 'anthropic' AND model_id = 'claude-sonnet-5-5'
   AND NOT ('identity_strong' = ANY(roles));

-- migrate:down
UPDATE public.llm_models
   SET roles = array_remove(array_remove(roles, 'identity'), 'identity_strong'),
       updated_at = now()
 WHERE roles && ARRAY['identity', 'identity_strong']::text[];
