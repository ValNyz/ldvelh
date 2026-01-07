-- ============================================================================
-- LDVELH - Schema BDD Complet
-- ============================================================================

-- Extension UUID
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================================
-- TABLE: parties
-- ============================================================================

CREATE TABLE parties (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  nom CHARACTER VARYING(255) DEFAULT 'Nouvelle partie',
  cycle_actuel INTEGER DEFAULT 1,
  jour CHARACTER VARYING(20),
  date_jeu CHARACTER VARYING(50),
  heure CHARACTER VARYING(10),
  lieu_actuel TEXT,
  pnjs_presents TEXT[],
  active BOOLEAN DEFAULT true,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

-- ============================================================================
-- TABLE: chat_messages
-- ============================================================================

CREATE TABLE chat_messages (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  partie_id UUID NOT NULL REFERENCES parties(id) ON DELETE CASCADE,
  role CHARACTER VARYING(20) NOT NULL,
  content TEXT NOT NULL,
  cycle INTEGER,
  lieu TEXT,
  pnjs_presents TEXT[],
  resume TEXT,
  state_snapshot JSONB,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE INDEX idx_messages_partie ON chat_messages(partie_id);
CREATE INDEX idx_messages_cycle ON chat_messages(partie_id, cycle);
CREATE INDEX idx_messages_cycle_resume ON chat_messages(partie_id, cycle) 
  WHERE resume IS NOT NULL;
CREATE INDEX idx_messages_lieu ON chat_messages(partie_id, lieu) 
  WHERE lieu IS NOT NULL;

-- ============================================================================
-- TABLE: cycle_resumes
-- ============================================================================

CREATE TABLE cycle_resumes (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  partie_id UUID NOT NULL REFERENCES parties(id) ON DELETE CASCADE,
  cycle INTEGER NOT NULL,
  jour CHARACTER VARYING(20),
  date_jeu CHARACTER VARYING(50),
  resume TEXT,
  evenements_cles JSONB,
  relations_modifiees JSONB,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE INDEX idx_resumes_partie ON cycle_resumes(partie_id, cycle);

-- ============================================================================
-- TABLE: kg_entites
-- ============================================================================

CREATE TABLE kg_entites (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  partie_id UUID NOT NULL REFERENCES parties(id) ON DELETE CASCADE,
  type CHARACTER VARYING(50) NOT NULL,
  nom CHARACTER VARYING(255) NOT NULL,
  alias TEXT[] DEFAULT '{}',
  proprietes JSONB DEFAULT '{}',
  confirme BOOLEAN DEFAULT true,
  cycle_creation INTEGER NOT NULL DEFAULT 1,
  cycle_disparition INTEGER,
  raison_disparition TEXT,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
  UNIQUE(partie_id, type, nom)
);

CREATE INDEX idx_kg_entites_partie ON kg_entites(partie_id);
CREATE INDEX idx_kg_entites_type ON kg_entites(partie_id, type);
CREATE INDEX idx_kg_entites_nom ON kg_entites(partie_id, nom);
CREATE INDEX idx_kg_entites_alias ON kg_entites USING GIN(alias);
CREATE INDEX idx_kg_entites_props ON kg_entites USING GIN(proprietes);
CREATE INDEX idx_kg_entites_actives ON kg_entites(partie_id) WHERE cycle_disparition IS NULL;
CREATE INDEX idx_kg_entites_objet ON kg_entites(partie_id, type) 
  WHERE type = 'objet' AND cycle_disparition IS NULL;

-- ============================================================================
-- TABLE: kg_relations
-- ============================================================================

CREATE TABLE kg_relations (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  partie_id UUID NOT NULL REFERENCES parties(id) ON DELETE CASCADE,
  source_id UUID NOT NULL REFERENCES kg_entites(id) ON DELETE CASCADE,
  cible_id UUID NOT NULL REFERENCES kg_entites(id) ON DELETE CASCADE,
  type_relation CHARACTER VARYING(100) NOT NULL,
  proprietes JSONB DEFAULT '{}',
  cycle_debut INTEGER NOT NULL,
  cycle_fin INTEGER,
  raison_fin TEXT,
  certitude CHARACTER VARYING(20) DEFAULT 'certain',
  verite BOOLEAN DEFAULT true,
  source_info CHARACTER VARYING(255),
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
  UNIQUE(partie_id, source_id, cible_id, type_relation, cycle_debut)
);

CREATE INDEX idx_kg_relations_partie ON kg_relations(partie_id);
CREATE INDEX idx_kg_relations_source ON kg_relations(source_id);
CREATE INDEX idx_kg_relations_cible ON kg_relations(cible_id);
CREATE INDEX idx_kg_relations_type ON kg_relations(partie_id, type_relation);
CREATE INDEX idx_kg_relations_actives ON kg_relations(partie_id) WHERE cycle_fin IS NULL;
CREATE INDEX idx_kg_relations_possede ON kg_relations(partie_id, source_id, type_relation) 
  WHERE type_relation = 'possede' AND cycle_fin IS NULL;

-- ============================================================================
-- TABLE: kg_etats
-- ============================================================================

CREATE TABLE kg_etats (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  partie_id UUID NOT NULL REFERENCES parties(id) ON DELETE CASCADE,
  entite_id UUID NOT NULL REFERENCES kg_entites(id) ON DELETE CASCADE,
  attribut CHARACTER VARYING(100) NOT NULL,
  valeur TEXT NOT NULL,
  details JSONB,
  cycle_debut INTEGER NOT NULL,
  cycle_fin INTEGER,
  certitude CHARACTER VARYING(20) DEFAULT 'certain',
  verite BOOLEAN DEFAULT true,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE INDEX idx_kg_etats_partie ON kg_etats(partie_id);
CREATE INDEX idx_kg_etats_entite ON kg_etats(entite_id);
CREATE INDEX idx_kg_etats_attribut ON kg_etats(entite_id, attribut);
CREATE INDEX idx_kg_etats_actifs ON kg_etats(entite_id) WHERE cycle_fin IS NULL;

-- ============================================================================
-- TABLE: kg_connaissances
-- ============================================================================

CREATE TABLE kg_connaissances (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  partie_id UUID NOT NULL REFERENCES parties(id) ON DELETE CASCADE,
  entite_id UUID NOT NULL REFERENCES kg_entites(id) ON DELETE CASCADE,
  attribut CHARACTER VARYING(100) NOT NULL,
  valeur TEXT NOT NULL,
  source_type CHARACTER VARYING(50) DEFAULT 'observation',
  cycle_decouverte INTEGER NOT NULL,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
  UNIQUE(partie_id, entite_id, attribut)
);

CREATE INDEX idx_kg_conn_partie ON kg_connaissances(partie_id);
CREATE INDEX idx_kg_conn_entite ON kg_connaissances(entite_id);

-- ============================================================================
-- TABLE: kg_evenements
-- ============================================================================

CREATE TABLE kg_evenements (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  partie_id UUID NOT NULL REFERENCES parties(id) ON DELETE CASCADE,
  type CHARACTER VARYING(50) NOT NULL,
  categorie CHARACTER VARYING(50),
  titre CHARACTER VARYING(255) NOT NULL,
  description TEXT,
  cycle INTEGER NOT NULL,
  heure CHARACTER VARYING(10),
  recurrence JSONB,
  lieu_id UUID REFERENCES kg_entites(id) ON DELETE SET NULL,
  montant INTEGER,
  realise BOOLEAN DEFAULT false,
  annule BOOLEAN DEFAULT false,
  raison_annulation TEXT,
  certitude CHARACTER VARYING(20) DEFAULT 'certain',
  verite BOOLEAN DEFAULT true,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE INDEX idx_kg_evenements_partie ON kg_evenements(partie_id);
CREATE INDEX idx_kg_evenements_cycle ON kg_evenements(partie_id, cycle);
CREATE INDEX idx_kg_evenements_type ON kg_evenements(partie_id, type);
CREATE INDEX idx_kg_evenements_planifies ON kg_evenements(partie_id, cycle) 
  WHERE type IN ('planifie', 'recurrent') AND realise = false AND annule = false;

-- ============================================================================
-- TABLE: kg_evenement_participants
-- ============================================================================

CREATE TABLE kg_evenement_participants (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  evenement_id UUID NOT NULL REFERENCES kg_evenements(id) ON DELETE CASCADE,
  entite_id UUID NOT NULL REFERENCES kg_entites(id) ON DELETE CASCADE,
  role CHARACTER VARYING(100),
  UNIQUE(evenement_id, entite_id)
);

CREATE INDEX idx_kg_ev_part_event ON kg_evenement_participants(evenement_id);
CREATE INDEX idx_kg_ev_part_entite ON kg_evenement_participants(entite_id);

-- ============================================================================
-- TABLE: kg_extraction_logs
-- ============================================================================

CREATE TABLE kg_extraction_logs (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  partie_id UUID NOT NULL REFERENCES parties(id) ON DELETE CASCADE,
  cycle INTEGER NOT NULL,
  duree_ms INTEGER,
  nb_operations INTEGER DEFAULT 0,
  nb_entites_creees INTEGER DEFAULT 0,
  nb_relations_creees INTEGER DEFAULT 0,
  nb_evenements_crees INTEGER DEFAULT 0,
  nb_etats_modifies INTEGER DEFAULT 0,
  nb_contradictions INTEGER DEFAULT 0,
  nb_entites_non_resolues INTEGER DEFAULT 0,
  nb_operations_invalides INTEGER DEFAULT 0,
  contradictions JSONB,
  erreurs JSONB,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE INDEX idx_kg_logs_partie ON kg_extraction_logs(partie_id);
CREATE INDEX idx_kg_logs_cycle ON kg_extraction_logs(partie_id, cycle);

-- ============================================================================
-- FONCTIONS
-- ============================================================================

-- Trouver une entité par nom ou alias
CREATE OR REPLACE FUNCTION kg_trouver_entite(
  p_partie_id UUID,
  p_nom TEXT,
  p_type CHARACTER VARYING DEFAULT NULL
)
RETURNS UUID AS $$
DECLARE
  v_id UUID;
  v_nom_lower TEXT := LOWER(TRIM(p_nom));
BEGIN
  -- Match exact sur nom
  SELECT id INTO v_id
  FROM kg_entites
  WHERE partie_id = p_partie_id
    AND (p_type IS NULL OR type = p_type)
    AND cycle_disparition IS NULL
    AND LOWER(nom) = v_nom_lower
  LIMIT 1;
  
  IF v_id IS NOT NULL THEN RETURN v_id; END IF;
  
  -- Match sur alias
  SELECT id INTO v_id
  FROM kg_entites
  WHERE partie_id = p_partie_id
    AND (p_type IS NULL OR type = p_type)
    AND cycle_disparition IS NULL
    AND v_nom_lower = ANY(SELECT LOWER(unnest(alias)))
  LIMIT 1;
  
  IF v_id IS NOT NULL THEN RETURN v_id; END IF;
  
  -- Match partiel (prénom seul)
  SELECT id INTO v_id
  FROM kg_entites
  WHERE partie_id = p_partie_id
    AND (p_type IS NULL OR type = p_type)
    AND cycle_disparition IS NULL
    AND (
      LOWER(nom) LIKE v_nom_lower || ' %'
      OR LOWER(nom) LIKE '% ' || v_nom_lower
    )
  LIMIT 1;
  
  RETURN v_id;
END;
$$ LANGUAGE plpgsql;

-- Créer ou mettre à jour une entité
CREATE OR REPLACE FUNCTION kg_upsert_entite(
  p_partie_id UUID,
  p_type CHARACTER VARYING,
  p_nom CHARACTER VARYING,
  p_alias TEXT[] DEFAULT '{}',
  p_proprietes JSONB DEFAULT '{}',
  p_cycle INTEGER DEFAULT 1,
  p_confirme BOOLEAN DEFAULT true
)
RETURNS UUID AS $$
DECLARE
  v_id UUID;
  v_existing_alias TEXT[];
  v_existing_props JSONB;
BEGIN
  v_id := kg_trouver_entite(p_partie_id, p_nom, p_type);
  
  IF v_id IS NOT NULL THEN
    SELECT alias, proprietes INTO v_existing_alias, v_existing_props
    FROM kg_entites WHERE id = v_id;
    
    UPDATE kg_entites SET
      proprietes = v_existing_props || p_proprietes,
      alias = ARRAY(SELECT DISTINCT unnest(v_existing_alias || p_alias)),
      confirme = GREATEST(confirme::int, p_confirme::int)::boolean,
      updated_at = NOW()
    WHERE id = v_id;
    
    RETURN v_id;
  ELSE
    INSERT INTO kg_entites (partie_id, type, nom, alias, proprietes, cycle_creation, confirme)
    VALUES (p_partie_id, p_type, p_nom, p_alias, p_proprietes, p_cycle, p_confirme)
    RETURNING id INTO v_id;
    
    RETURN v_id;
  END IF;
END;
$$ LANGUAGE plpgsql;

-- Créer ou mettre à jour une relation
CREATE OR REPLACE FUNCTION kg_upsert_relation(
  p_partie_id UUID,
  p_source_id UUID,
  p_cible_id UUID,
  p_type CHARACTER VARYING,
  p_proprietes JSONB DEFAULT '{}',
  p_cycle INTEGER DEFAULT 1,
  p_certitude CHARACTER VARYING DEFAULT 'certain',
  p_verite BOOLEAN DEFAULT true,
  p_source_info CHARACTER VARYING DEFAULT NULL
)
RETURNS UUID AS $$
DECLARE
  v_id UUID;
  v_existing_props JSONB;
BEGIN
  SELECT id, proprietes INTO v_id, v_existing_props
  FROM kg_relations
  WHERE partie_id = p_partie_id
    AND source_id = p_source_id
    AND cible_id = p_cible_id
    AND type_relation = p_type
    AND cycle_fin IS NULL;
  
  IF v_id IS NOT NULL THEN
    UPDATE kg_relations SET
      proprietes = v_existing_props || p_proprietes,
      certitude = p_certitude,
      verite = p_verite,
      source_info = COALESCE(p_source_info, source_info)
    WHERE id = v_id;
    
    RETURN v_id;
  ELSE
    INSERT INTO kg_relations (
      partie_id, source_id, cible_id, type_relation,
      proprietes, cycle_debut, certitude, verite, source_info
    )
    VALUES (
      p_partie_id, p_source_id, p_cible_id, p_type,
      p_proprietes, p_cycle, p_certitude, p_verite, p_source_info
    )
    RETURNING id INTO v_id;
    
    RETURN v_id;
  END IF;
END;
$$ LANGUAGE plpgsql;

-- Terminer une relation
CREATE OR REPLACE FUNCTION kg_terminer_relation(
  p_partie_id UUID,
  p_source_nom TEXT,
  p_cible_nom TEXT,
  p_type CHARACTER VARYING,
  p_cycle INTEGER,
  p_raison TEXT DEFAULT NULL
)
RETURNS BOOLEAN AS $$
DECLARE
  v_source_id UUID;
  v_cible_id UUID;
BEGIN
  v_source_id := kg_trouver_entite(p_partie_id, p_source_nom);
  v_cible_id := kg_trouver_entite(p_partie_id, p_cible_nom);
  
  IF v_source_id IS NULL OR v_cible_id IS NULL THEN
    RETURN false;
  END IF;
  
  UPDATE kg_relations SET
    cycle_fin = p_cycle,
    raison_fin = p_raison
  WHERE partie_id = p_partie_id
    AND source_id = v_source_id
    AND cible_id = v_cible_id
    AND type_relation = p_type
    AND cycle_fin IS NULL;
  
  RETURN FOUND;
END;
$$ LANGUAGE plpgsql;

-- Mettre à jour un état
CREATE OR REPLACE FUNCTION kg_set_etat(
  p_partie_id UUID,
  p_entite_id UUID,
  p_attribut CHARACTER VARYING,
  p_valeur TEXT,
  p_cycle INTEGER,
  p_details JSONB DEFAULT NULL,
  p_certitude CHARACTER VARYING DEFAULT 'certain',
  p_verite BOOLEAN DEFAULT true
)
RETURNS UUID AS $$
DECLARE
  v_id UUID;
  v_old_valeur TEXT;
BEGIN
  SELECT valeur INTO v_old_valeur
  FROM kg_etats
  WHERE entite_id = p_entite_id
    AND attribut = p_attribut
    AND cycle_fin IS NULL;
  
  IF v_old_valeur = p_valeur THEN
    RETURN NULL;
  END IF;
  
  UPDATE kg_etats SET cycle_fin = p_cycle
  WHERE entite_id = p_entite_id
    AND attribut = p_attribut
    AND cycle_fin IS NULL;
  
  INSERT INTO kg_etats (
    partie_id, entite_id, attribut, valeur, 
    details, cycle_debut, certitude, verite
  )
  VALUES (
    p_partie_id, p_entite_id, p_attribut, p_valeur,
    p_details, p_cycle, p_certitude, p_verite
  )
  RETURNING id INTO v_id;
  
  RETURN v_id;
END;
$$ LANGUAGE plpgsql;

-- Apprendre une connaissance
CREATE OR REPLACE FUNCTION kg_apprendre(
  p_partie_id UUID,
  p_entite_id UUID,
  p_attribut CHARACTER VARYING,
  p_valeur TEXT,
  p_cycle INTEGER,
  p_source_type CHARACTER VARYING DEFAULT 'observation'
)
RETURNS UUID AS $$
DECLARE
  v_id UUID;
BEGIN
  INSERT INTO kg_connaissances (
    partie_id, entite_id, attribut, valeur, cycle_decouverte, source_type
  )
  VALUES (
    p_partie_id, p_entite_id, p_attribut, p_valeur, p_cycle, p_source_type
  )
  ON CONFLICT (partie_id, entite_id, attribut) 
  DO UPDATE SET 
    valeur = EXCLUDED.valeur,
    source_type = EXCLUDED.source_type
  RETURNING id INTO v_id;
  
  RETURN v_id;
END;
$$ LANGUAGE plpgsql;

-- Transaction de crédits
CREATE OR REPLACE FUNCTION kg_transaction_credits(
  p_partie_id UUID,
  p_montant INTEGER,
  p_cycle INTEGER,
  p_description TEXT DEFAULT NULL
)
RETURNS TABLE(success BOOLEAN, nouveau_solde INTEGER, erreur TEXT) AS $$
DECLARE
  v_protagoniste_id UUID;
  v_solde_actuel INTEGER;
  v_nouveau_solde INTEGER;
BEGIN
  SELECT id INTO v_protagoniste_id
  FROM kg_entites
  WHERE partie_id = p_partie_id
    AND type = 'protagoniste'
    AND cycle_disparition IS NULL;
  
  IF v_protagoniste_id IS NULL THEN
    RETURN QUERY SELECT false, 0, 'Protagoniste non trouvé'::TEXT;
    RETURN;
  END IF;
  
  SELECT COALESCE(e.valeur::INTEGER, 1400) INTO v_solde_actuel
  FROM kg_etats e
  WHERE e.entite_id = v_protagoniste_id
    AND e.attribut = 'credits'
    AND e.cycle_fin IS NULL
  FOR UPDATE;
  
  IF v_solde_actuel IS NULL THEN
    v_solde_actuel := 1400;
  END IF;
  
  v_nouveau_solde := v_solde_actuel + p_montant;
  
  IF v_nouveau_solde < 0 THEN
    RETURN QUERY SELECT 
      false, 
      v_solde_actuel, 
      format('Solde insuffisant: %s + (%s) = %s', v_solde_actuel, p_montant, v_nouveau_solde)::TEXT;
    RETURN;
  END IF;
  
  PERFORM kg_set_etat(
    p_partie_id,
    v_protagoniste_id,
    'credits',
    v_nouveau_solde::TEXT,
    p_cycle,
    jsonb_build_object('description', p_description, 'montant', p_montant),
    'certain',
    true
  );
  
  RETURN QUERY SELECT true, v_nouveau_solde, NULL::TEXT;
END;
$$ LANGUAGE plpgsql;

-- Mise à jour d'une jauge
CREATE OR REPLACE FUNCTION kg_update_jauge(
  p_partie_id UUID,
  p_attribut CHARACTER VARYING,
  p_delta NUMERIC,
  p_cycle INTEGER
)
RETURNS TABLE(success BOOLEAN, ancienne_valeur NUMERIC, nouvelle_valeur NUMERIC) AS $$
DECLARE
  v_protagoniste_id UUID;
  v_valeur_actuelle NUMERIC;
  v_nouvelle_valeur NUMERIC;
  v_min NUMERIC := 0;
  v_max NUMERIC := 5;
  v_arrondi NUMERIC := 0.5;
BEGIN
  IF p_attribut NOT IN ('energie', 'moral', 'sante') THEN
    RETURN QUERY SELECT false, 0::NUMERIC, 0::NUMERIC;
    RETURN;
  END IF;
  
  SELECT id INTO v_protagoniste_id
  FROM kg_entites
  WHERE partie_id = p_partie_id
    AND type = 'protagoniste'
    AND cycle_disparition IS NULL;
  
  IF v_protagoniste_id IS NULL THEN
    RETURN QUERY SELECT false, 0::NUMERIC, 0::NUMERIC;
    RETURN;
  END IF;
  
  SELECT COALESCE(e.valeur::NUMERIC, 3) INTO v_valeur_actuelle
  FROM kg_etats e
  WHERE e.entite_id = v_protagoniste_id
    AND e.attribut = p_attribut
    AND e.cycle_fin IS NULL
  FOR UPDATE;
  
  IF v_valeur_actuelle IS NULL THEN
    v_valeur_actuelle := 3;
  END IF;
  
  v_nouvelle_valeur := v_valeur_actuelle + p_delta;
  v_nouvelle_valeur := ROUND(v_nouvelle_valeur / v_arrondi) * v_arrondi;
  v_nouvelle_valeur := GREATEST(v_min, LEAST(v_max, v_nouvelle_valeur));
  
  IF v_nouvelle_valeur != v_valeur_actuelle THEN
    PERFORM kg_set_etat(
      p_partie_id,
      v_protagoniste_id,
      p_attribut,
      v_nouvelle_valeur::TEXT,
      p_cycle,
      NULL,
      'certain',
      true
    );
  END IF;
  
  RETURN QUERY SELECT true, v_valeur_actuelle, v_nouvelle_valeur;
END;
$$ LANGUAGE plpgsql;

-- Valeur totale de l'inventaire
CREATE OR REPLACE FUNCTION kg_valeur_inventaire(p_partie_id UUID)
RETURNS TABLE(valeur_totale INTEGER, nb_objets INTEGER, par_categorie JSONB) AS $$
BEGIN
  RETURN QUERY
  SELECT 
    COALESCE(SUM(v.valeur_neuve * v.quantite)::int, 0) AS valeur_totale,
    COALESCE(SUM(v.quantite)::int, 0) AS nb_objets,
    COALESCE(
      jsonb_object_agg(
        COALESCE(v.categorie, 'autre'),
        jsonb_build_object(
          'count', cat_counts.cnt,
          'valeur', cat_counts.val
        )
      ),
      '{}'::jsonb
    ) AS par_categorie
  FROM kg_v_inventaire v
  LEFT JOIN LATERAL (
    SELECT 
      COALESCE(vi.categorie, 'autre') AS cat,
      SUM(vi.quantite)::int AS cnt,
      SUM(vi.valeur_neuve * vi.quantite)::int AS val
    FROM kg_v_inventaire vi
    WHERE vi.partie_id = p_partie_id
    GROUP BY COALESCE(vi.categorie, 'autre')
  ) cat_counts ON cat_counts.cat = COALESCE(v.categorie, 'autre')
  WHERE v.partie_id = p_partie_id;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- VUES
-- ============================================================================

-- Relations actives avec noms résolus
CREATE OR REPLACE VIEW kg_v_relations_actives AS
SELECT 
  r.partie_id,
  r.id AS relation_id,
  r.source_id,
  e_source.type AS source_type,
  e_source.nom AS source_nom,
  r.type_relation,
  r.cible_id,
  e_cible.type AS cible_type,
  e_cible.nom AS cible_nom,
  r.proprietes,
  r.cycle_debut,
  r.certitude,
  r.verite
FROM kg_relations r
JOIN kg_entites e_source ON r.source_id = e_source.id
JOIN kg_entites e_cible ON r.cible_id = e_cible.id
WHERE r.cycle_fin IS NULL
  AND e_source.cycle_disparition IS NULL
  AND e_cible.cycle_disparition IS NULL;

-- États actuels avec noms résolus
CREATE OR REPLACE VIEW kg_v_etats_actuels AS
SELECT 
  e.partie_id,
  e.entite_id,
  ent.type AS entite_type,
  ent.nom AS entite_nom,
  e.attribut,
  e.valeur,
  e.details,
  e.cycle_debut,
  e.certitude,
  e.verite
FROM kg_etats e
JOIN kg_entites ent ON e.entite_id = ent.id
WHERE e.cycle_fin IS NULL
  AND ent.cycle_disparition IS NULL;

-- Connaissances actives (ce que Valentin sait)
CREATE OR REPLACE VIEW kg_v_connaissances_actives AS
SELECT 
  c.partie_id,
  e.nom AS entite_nom,
  c.attribut,
  c.valeur,
  c.source_type,
  c.cycle_decouverte
FROM kg_connaissances c
JOIN kg_entites e ON c.entite_id = e.id
WHERE e.cycle_disparition IS NULL;

-- Événements à venir
CREATE OR REPLACE VIEW kg_v_evenements_a_venir AS
SELECT 
  ev.id,
  ev.partie_id,
  ev.type,
  ev.categorie,
  ev.titre,
  ev.description,
  ev.cycle,
  ev.heure,
  ev.recurrence,
  ev.lieu_id,
  ev.montant,
  ev.realise,
  ev.annule,
  ev.raison_annulation,
  ev.certitude,
  ev.verite,
  ev.created_at,
  l.nom AS lieu_nom,
  array_agg(DISTINCT ent.nom) FILTER (WHERE ent.nom IS NOT NULL) AS participants
FROM kg_evenements ev
LEFT JOIN kg_entites l ON ev.lieu_id = l.id
LEFT JOIN kg_evenement_participants ep ON ev.id = ep.evenement_id
LEFT JOIN kg_entites ent ON ep.entite_id = ent.id
WHERE ev.type IN ('planifie', 'recurrent')
  AND ev.realise = false
  AND ev.annule = false
GROUP BY ev.id, l.nom;

-- Inventaire de Valentin
CREATE OR REPLACE VIEW kg_v_inventaire AS
SELECT 
  r.partie_id,
  e_objet.id AS objet_id,
  e_objet.nom AS objet_nom,
  e_objet.proprietes AS objet_props,
  r.proprietes AS relation_props,
  COALESCE((r.proprietes->>'quantite')::int, 1) AS quantite,
  COALESCE(r.proprietes->>'localisation', 'sur_soi') AS localisation,
  e_objet.proprietes->>'categorie' AS categorie,
  COALESCE(e_objet.proprietes->>'etat', 'bon') AS etat,
  COALESCE((e_objet.proprietes->>'valeur_neuve')::int, 0) AS valeur_neuve,
  COALESCE((e_objet.proprietes->>'prix_achat')::int, 0) AS prix_achat,
  r.proprietes->>'origine' AS origine,
  r.proprietes->>'prete_a' AS prete_a,
  (r.proprietes->>'prete_depuis_cycle')::int AS prete_depuis_cycle
FROM kg_relations r
JOIN kg_entites e_val ON r.source_id = e_val.id AND e_val.type = 'protagoniste'
JOIN kg_entites e_objet ON r.cible_id = e_objet.id AND e_objet.type = 'objet'
WHERE r.type_relation = 'possede'
  AND r.cycle_fin IS NULL
  AND e_objet.cycle_disparition IS NULL;

-- Inventaire groupé par localisation
CREATE OR REPLACE VIEW kg_v_inventaire_par_localisation AS
SELECT 
  partie_id,
  localisation,
  json_agg(
    json_build_object(
      'objet_id', objet_id,
      'objet_nom', objet_nom,
      'quantite', quantite,
      'categorie', categorie,
      'etat', etat,
      'valeur_neuve', valeur_neuve
    ) ORDER BY categorie, objet_nom
  ) AS objets,
  SUM(quantite) AS total_objets,
  SUM(valeur_neuve * quantite) AS valeur_totale
FROM kg_v_inventaire
GROUP BY partie_id, localisation;

-- Possessions des PNJ
CREATE OR REPLACE VIEW kg_v_possessions_pnj AS
SELECT 
  r.partie_id,
  e_pnj.id AS pnj_id,
  e_pnj.nom AS pnj_nom,
  e_objet.id AS objet_id,
  e_objet.nom AS objet_nom,
  e_objet.proprietes AS objet_props,
  COALESCE((r.proprietes->>'quantite')::int, 1) AS quantite,
  r.proprietes->>'origine' AS origine,
  r.cycle_debut AS depuis_cycle
FROM kg_relations r
JOIN kg_entites e_pnj ON r.source_id = e_pnj.id AND e_pnj.type = 'personnage'
JOIN kg_entites e_objet ON r.cible_id = e_objet.id AND e_objet.type = 'objet'
WHERE r.type_relation = 'possede'
  AND r.cycle_fin IS NULL
  AND e_objet.cycle_disparition IS NULL;

-- Données tooltip pour les entités
CREATE OR REPLACE VIEW kg_v_tooltip AS
SELECT 
  e.id AS entite_id,
  e.partie_id,
  e.type AS entite_type,
  e.nom AS entite_nom,
  e.alias,
  COALESCE(
    (SELECT jsonb_object_agg(c.attribut, c.valeur)
     FROM kg_connaissances c
     WHERE c.entite_id = e.id),
    '{}'::jsonb
  ) AS connaissances,
  (SELECT jsonb_build_object('type', r.type_relation, 'props', r.proprietes)
   FROM kg_relations r
   JOIN kg_entites proto ON r.source_id = proto.id AND proto.type = 'protagoniste'
   WHERE r.cible_id = e.id
     AND r.cycle_fin IS NULL
     AND proto.partie_id = e.partie_id
   LIMIT 1
  ) AS relation_valentin
FROM kg_entites e
WHERE e.cycle_disparition IS NULL;
