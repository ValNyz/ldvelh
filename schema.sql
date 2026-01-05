-- ============================================================================
-- LDVELH - Schema BDD Complet
-- ============================================================================

-- Extension UUID
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================================
-- TABLE PARTIES (principale)
-- ============================================================================

CREATE TABLE parties (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  nom VARCHAR(255) DEFAULT 'Nouvelle partie',
  cycle_actuel INTEGER DEFAULT 1,
  jour VARCHAR(20),
  date_jeu VARCHAR(50),
  heure VARCHAR(10),
  lieu_actuel TEXT,
  pnjs_presents TEXT[],
  active BOOLEAN DEFAULT true,
  options JSONB DEFAULT '{"faits_enabled": true}',
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);


-- ============================================================================
-- TABLE SCENES
-- ============================================================================

CREATE TABLE scenes (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  partie_id UUID NOT NULL REFERENCES parties(id) ON DELETE CASCADE,
  cycle INTEGER NOT NULL,
  lieu VARCHAR(255) NOT NULL,
  numero INTEGER NOT NULL,
  heure_debut VARCHAR(10),
  heure_fin VARCHAR(10),
  resume TEXT,
  resume_intermediaire TEXT[],
  dernier_message_resume_id UUID,
  pnj_impliques TEXT[],
  statut VARCHAR(20) DEFAULT 'en_cours', -- 'en_cours', 'terminee', 'analysee'
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_scenes_partie_cycle ON scenes(partie_id, cycle);
CREATE INDEX idx_scenes_statut ON scenes(partie_id, statut);

-- ============================================================================
-- TABLE CHAT MESSAGES
-- ============================================================================

CREATE TABLE chat_messages (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  partie_id UUID NOT NULL REFERENCES parties(id) ON DELETE CASCADE,
  scene_id UUID REFERENCES scenes(id),
  role VARCHAR(20) NOT NULL,
  content TEXT NOT NULL,
  cycle INTEGER,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_messages_partie ON chat_messages(partie_id);
CREATE INDEX idx_messages_scene ON chat_messages(scene_id);
CREATE INDEX idx_messages_cycle ON chat_messages(partie_id, cycle);

-- ============================================================================
-- TABLE CYCLE RESUMES
-- ============================================================================

CREATE TABLE cycle_resumes (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  partie_id UUID NOT NULL REFERENCES parties(id) ON DELETE CASCADE,
  cycle INTEGER NOT NULL,
  jour VARCHAR(20),
  date_jeu VARCHAR(50),
  resume TEXT,
  evenements_cles JSONB,
  relations_modifiees JSONB,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_resumes_partie ON cycle_resumes(partie_id, cycle);
