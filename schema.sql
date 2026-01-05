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
-- TABLE VALENTIN (protagoniste)
-- ============================================================================

CREATE TABLE valentin (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  partie_id UUID NOT NULL REFERENCES parties(id) ON DELETE CASCADE,
  energie REAL DEFAULT 3,
  moral REAL DEFAULT 3,
  sante REAL DEFAULT 5,
  credits INTEGER DEFAULT 1400,
  logement INTEGER DEFAULT 0,
  traits TEXT[],
  hobbies TEXT[],
  inventaire TEXT[],
  raison_depart TEXT,
  poste TEXT,
  logement_adresse TEXT,
  logement_etat TEXT,
  logement_repare TEXT[],
  logement_a_faire TEXT[],
  logement_mobilier TEXT[],
  competences JSONB,
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- TABLE IA PERSONNELLE
-- ============================================================================

CREATE TABLE ia_personnelle (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  partie_id UUID NOT NULL REFERENCES parties(id) ON DELETE CASCADE,
  nom VARCHAR(100),
  traits TEXT[] DEFAULT ARRAY['sarcastique', 'pragmatique'],
  citations TEXT[]
);

-- ============================================================================
-- TABLE PNJ
-- ============================================================================

CREATE TABLE pnj (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  partie_id UUID NOT NULL REFERENCES parties(id) ON DELETE CASCADE,
  nom VARCHAR(255) NOT NULL,
  age INTEGER,
  espece VARCHAR(100),
  metier VARCHAR(255),
  physique TEXT,
  domicile VARCHAR(255),
  relation NUMERIC DEFAULT 0,
  disposition VARCHAR(50) DEFAULT 'neutre',
  dernier_contact INTEGER,
  cycles_vus INTEGER[],
  etape_romantique INTEGER DEFAULT 0,
  stat_social INTEGER DEFAULT 3,
  stat_travail INTEGER DEFAULT 3,
  stat_sante INTEGER DEFAULT 3,
  traits TEXT[],
  hobbies TEXT[],
  arc TEXT,
  citations TEXT[],
  est_initial BOOLEAN DEFAULT false,
  interet_romantique BOOLEAN DEFAULT false,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_pnj_partie ON pnj(partie_id);
CREATE INDEX idx_pnj_dernier_contact ON pnj(partie_id, dernier_contact);

-- ============================================================================
-- TABLE LIEUX
-- ============================================================================

CREATE TABLE lieux (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  partie_id UUID NOT NULL REFERENCES parties(id) ON DELETE CASCADE,
  nom VARCHAR(255) NOT NULL,
  type VARCHAR(100),
  secteur VARCHAR(255),
  description TEXT,
  horaires VARCHAR(100),
  pnjs_frequents TEXT[],
  cycles_visites INTEGER[],
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_lieux_partie ON lieux(partie_id);

-- ============================================================================
-- TABLE SCENES (NOUVEAU)
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
-- TABLE MESSAGES (in-game : SMS, emails reçus par Valentin)
-- ============================================================================

CREATE TABLE messages (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  partie_id UUID NOT NULL REFERENCES parties(id) ON DELETE CASCADE,
  cycle INTEGER,
  heure VARCHAR(10),
  expediteur VARCHAR(255),
  type VARCHAR(50), -- 'sms', 'email', 'notification', etc.
  contenu TEXT,
  lu BOOLEAN DEFAULT false,
  important BOOLEAN DEFAULT false,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_ingame_messages_partie ON messages(partie_id);

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

-- ============================================================================
-- TABLE FAITS (mémoire long terme)
-- ============================================================================

CREATE TABLE faits (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  partie_id UUID NOT NULL REFERENCES parties(id) ON DELETE CASCADE,
  sujet_type TEXT, -- 'pnj', 'lieu', 'valentin', 'monde', 'objet'
  sujet_id UUID,
  sujet_nom TEXT NOT NULL,
  categorie TEXT, -- 'etat', 'relation', 'evenement', 'promesse', 'connaissance', 'secret', 'trait', 'objectif'
  aspect TEXT, -- sous-catégorie pour déduplication
  fait TEXT NOT NULL,
  importance INTEGER DEFAULT 3,
  cycle_creation INTEGER,
  cycle_invalidation INTEGER,
  raison_invalidation TEXT,
  source TEXT,
  valentin_sait BOOLEAN DEFAULT true,
  certitude TEXT DEFAULT 'certain', -- 'certain', 'probable', 'rumeur'
  metadata JSONB,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_faits_partie ON faits(partie_id);
CREATE INDEX idx_faits_sujet ON faits(partie_id, sujet_nom);
CREATE INDEX idx_faits_importance ON faits(partie_id, importance);
CREATE INDEX idx_faits_categorie ON faits(partie_id, categorie);

-- ============================================================================
-- TABLE FINANCES
-- ============================================================================

CREATE TABLE finances (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  partie_id UUID NOT NULL REFERENCES parties(id) ON DELETE CASCADE,
  cycle INTEGER,
  heure VARCHAR(10),
  type VARCHAR(50), -- 'achat', 'vente', 'salaire', 'loyer', etc.
  montant INTEGER NOT NULL,
  objet VARCHAR(255),
  quantite INTEGER DEFAULT 1,
  description VARCHAR(500),
  created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_finances_partie ON finances(partie_id);
CREATE INDEX idx_finances_cycle ON finances(partie_id, cycle);

-- ============================================================================
-- TABLE ARCS NARRATIFS
-- ============================================================================

CREATE TABLE arcs (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  partie_id UUID NOT NULL REFERENCES parties(id) ON DELETE CASCADE,
  nom VARCHAR(255),
  type VARCHAR(100), -- 'travail', 'personnel', 'romance', 'exploration', 'mystere'
  description TEXT,
  etat VARCHAR(50) DEFAULT 'actif', -- 'actif', 'en_pause', 'termine', 'abandonne'
  progression INTEGER DEFAULT 0,
  obstacles TEXT[],
  pnj_impliques TEXT[],
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_arcs_partie ON arcs(partie_id);

-- ============================================================================
-- TABLE ARC EVENEMENTS
-- ============================================================================

CREATE TABLE arc_evenements (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  arc_id UUID NOT NULL REFERENCES arcs(id) ON DELETE CASCADE,
  cycle INTEGER,
  description TEXT,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_arc_events ON arc_evenements(arc_id);

-- ============================================================================
-- TABLE A VENIR (événements planifiés)
-- ============================================================================

CREATE TABLE a_venir (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  partie_id UUID NOT NULL REFERENCES parties(id) ON DELETE CASCADE,
  cycle_prevu INTEGER,
  evenement TEXT,
  type VARCHAR(100),
  pnj_impliques TEXT[],
  lieu VARCHAR(255),
  realise BOOLEAN DEFAULT false,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_avenir_partie ON a_venir(partie_id);
CREATE INDEX idx_avenir_cycle ON a_venir(partie_id, cycle_prevu);

-- ============================================================================
-- FONCTION RPC : UPSERT FAITS BATCH (utilisée par faitsService)
-- ============================================================================

CREATE OR REPLACE FUNCTION upsert_faits_batch(
  p_partie_id UUID,
  p_faits JSONB
)
RETURNS JSONB AS $$
DECLARE
  fait JSONB;
  v_inserted INTEGER := 0;
  v_updated INTEGER := 0;
  v_existing_id UUID;
BEGIN
  FOR fait IN SELECT * FROM jsonb_array_elements(p_faits)
  LOOP
    -- Chercher un fait existant avec même sujet + catégorie + aspect
    SELECT id INTO v_existing_id
    FROM faits
    WHERE partie_id = p_partie_id
      AND LOWER(sujet_nom) = LOWER(fait->>'sujet_nom')
      AND categorie = fait->>'categorie'
      AND (aspect = fait->>'aspect' OR (aspect IS NULL AND fait->>'aspect' IS NULL))
      AND cycle_invalidation IS NULL
    LIMIT 1;
    
    IF v_existing_id IS NOT NULL THEN
      -- Update
      UPDATE faits SET
        fait = fait->>'fait',
        importance = COALESCE((fait->>'importance')::INTEGER, importance),
        valentin_sait = COALESCE((fait->>'valentin_sait')::BOOLEAN, valentin_sait),
        updated_at = NOW()
      WHERE id = v_existing_id;
      v_updated := v_updated + 1;
    ELSE
      -- Insert
      INSERT INTO faits (
        partie_id, sujet_type, sujet_id, sujet_nom, categorie, aspect,
        fait, importance, cycle_creation, valentin_sait, certitude
      ) VALUES (
        p_partie_id,
        fait->>'sujet_type',
        (fait->>'sujet_id')::UUID,
        fait->>'sujet_nom',
        fait->>'categorie',
        fait->>'aspect',
        fait->>'fait',
        COALESCE((fait->>'importance')::INTEGER, 3),
        COALESCE((fait->>'cycle_creation')::INTEGER, 1),
        COALESCE((fait->>'valentin_sait')::BOOLEAN, true),
        COALESCE(fait->>'certitude', 'certain')
      );
      v_inserted := v_inserted + 1;
    END IF;
  END LOOP;
  
  RETURN jsonb_build_object('inserted', v_inserted, 'updated', v_updated);
END;
$$ LANGUAGE plpgsql;
