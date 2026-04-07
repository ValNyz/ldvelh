-- migrate:up

-- ============================================================================
-- NPC ENGINE EXTENSION TABLES (FK to characters)
-- Lighter than protagonist tables: skills/traits as JSONB.
-- ============================================================================

CREATE TABLE npc_fate (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  character_id UUID UNIQUE NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
  aspects JSONB DEFAULT '[]',           -- [{name, type}]
  skills JSONB DEFAULT '{}',            -- {"Combat": 3, "Athlétisme": 2}
  stunts JSONB DEFAULT '[]',            -- [{name, description}]
  stress_physical BOOLEAN[] DEFAULT '{f,f}',  -- 2 boxes by default for NPCs
  stress_mental BOOLEAN[] DEFAULT '{f,f}',
  consequences JSONB DEFAULT '{}',      -- {mild: null, moderate: null}
  fate_points INTEGER DEFAULT 1,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE npc_d6 (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  character_id UUID UNIQUE NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
  attributes JSONB DEFAULT '{}',        -- {"Dexterite": "3D", "Force": "2D+1"}
  skills JSONB DEFAULT '{}',            -- {"Esquive": "4D", "Blasters": "3D+2"}
  wounds JSONB DEFAULT '{}',
  force_points INTEGER DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE npc_narrative (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  character_id UUID UNIQUE NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
  traits JSONB DEFAULT '[]',            -- [{name, description}]
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_npc_fate_char ON npc_fate(character_id);
CREATE INDEX idx_npc_d6_char ON npc_d6(character_id);
CREATE INDEX idx_npc_narrative_char ON npc_narrative(character_id);


-- migrate:down

DROP TABLE IF EXISTS npc_narrative;
DROP TABLE IF EXISTS npc_d6;
DROP TABLE IF EXISTS npc_fate;
