-- migrate:up
CREATE TABLE public.llm_models (
    provider        varchar(32)  NOT NULL,
    model_id        varchar(200) NOT NULL,
    label           varchar(200) NOT NULL,
    status          varchar(16)  NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('enabled', 'pending', 'failed', 'retired')),
    roles           text[]       NOT NULL DEFAULT '{}',
    default_rank    integer,             -- provider preference order for default roles (lower first)
    input_price     numeric(12, 6),      -- USD per million tokens
    output_price    numeric(12, 6),
    cache_write_price numeric(12, 6),
    cache_read_price  numeric(12, 6),
    profile         jsonb        NOT NULL DEFAULT '{}',
    probe_results   jsonb,
    source          varchar(16)  NOT NULL DEFAULT 'auto' CHECK (source IN ('auto', 'manual')),
    last_probed_at  timestamptz,
    updated_at      timestamptz  NOT NULL DEFAULT now(),
    PRIMARY KEY (provider, model_id)
);
CREATE INDEX idx_llm_models_enabled ON public.llm_models (provider) WHERE status = 'enabled';

-- Seed: today's offer, so behavior is unchanged on day one.
INSERT INTO public.llm_models (provider, model_id, label, status, roles, default_rank, profile, source) VALUES
 ('anthropic', 'claude-sonnet-5-5', 'Sonnet 5.5', 'enabled', '{narration}', 1,
  '{"send_temperature": false, "force_tool": false, "thinking": {"type": "between_tools"}}', 'manual'),
 ('anthropic', 'claude-haiku-5-5', 'Haiku 5.5', 'enabled', '{mechanical}', 2,
  '{"send_temperature": false, "force_tool": false, "thinking": {"type": "disabled"}}', 'manual'),
 ('anthropic', 'claude-opus-5-5', 'Opus 5.5', 'enabled', '{}', 3,
  '{"send_temperature": false, "force_tool": false, "thinking_headroom": 16000}', 'manual'),
 ('anthropic', 'claude-fable-5-1', 'Fable 5.1', 'enabled', '{}', 4,
  '{"send_temperature": false, "force_tool": false, "thinking_headroom": 16000}', 'manual'),
 ('mistral', 'mistral-large-latest', 'mistral-large-latest', 'enabled', '{narration,mechanical}', 1, '{}', 'auto'),
 ('nous', 'google/gemini-4-argon', 'google/gemini-4-argon', 'pending', '{}', 1, '{}', 'auto'),
 ('nous', 'anthropic/claude-haiku-5.5', 'anthropic/claude-haiku-5.5', 'pending', '{}', 2, '{}', 'auto'),
 ('wandb', 'google/gemma-4-31B-it', 'google/gemma-4-31B-it', 'pending', '{}', 1, '{}', 'auto'),
 ('wandb', 'deepseek-ai/DeepSeek-V4-Pro-0813', 'deepseek-ai/DeepSeek-V4-Pro-0813', 'pending', '{}', 2, '{}', 'auto');

-- migrate:down
DROP TABLE public.llm_models;
