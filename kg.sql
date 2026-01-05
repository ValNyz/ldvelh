-- ============================================================================
-- KNOWLEDGE GRAPH POUR LDVELH
-- Remplace : valentin, ia_personnelle, pnj, lieux, arcs, faits
-- ============================================================================

-- ============================================================================
-- ENTITÉS (Nœuds du graphe)
-- ============================================================================

CREATE TABLE kg_entites (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  partie_id UUID NOT NULL REFERENCES parties(id) ON DELETE CASCADE,
  
  -- Identification
  type VARCHAR(50) NOT NULL,
  /*
    Types d'entités:
    - 'protagoniste' : Valentin (unique par partie)
    - 'ia' : IA personnelle de Valentin
    - 'personnage' : PNJ
    - 'lieu' : Endroits physiques (3 niveaux max: zone > secteur > lieu)
    - 'organisation' : Entreprises, groupes, factions
    - 'objet' : Items physiques
    - 'arc_narratif' : Arcs de l'histoire
  */
  
  nom VARCHAR(255) NOT NULL,
  alias TEXT[] DEFAULT '{}', -- Noms alternatifs pour matching
  
  -- Propriétés flexibles (JSONB)
  proprietes JSONB DEFAULT '{}',
  /*
    PROTAGONISTE (Valentin): {
      "physique": "1m78, brun dégarni, barbe, implants rétiniens",
      "traits": ["introverti", "maladroit en amour", "curieux"],
      "raison_depart": "...",
      "poste": "Architecte IA",
      "hobbies": ["cuisine", "..."],
      "competences": {
        "informatique": 5, "systemes": 4, "recherche": 4,
        "social": 2, "cuisine": 3, "bricolage": 3,
        "observation": 3, "culture": 3, "sang_froid": 3,
        "pedagogie": 3, "physique": 3, "administration": 3, "jeux": 3,
        "discretion": 2, "negociation": 2, "empathie": 2,
        "art": 2, "commerce": 2, "leadership": 2, "xenologie": 2,
        "medical": 1, "pilotage": 1, "mensonge": 1, "survie": 1,
        "intimidation": 1, "seduction": 1, "droit": 1, "botanique": 1
      }
    }
    
    IA: {
      "traits": ["sarcastique", "pragmatique"],
      "voix": "grave, sensuelle"
    }
    
    PERSONNAGE: {
      "age": 32,
      "espece": "humain",
      "metier": "serveuse", 
      "physique": "blonde, 1m54, courbes...",
      "traits": ["timide", "curieuse"],
      "interet_romantique": true
    }
    
    LIEU: {
      "niveau": "zone|secteur|lieu", -- Hiérarchie
      "type_lieu": "commerce|habitat|travail|public|loisir|transport|medical|administratif",
      "horaires": "8h-20h",
      "ambiance": "bruyant, populaire"
    }
    
    ORGANISATION: {
      "type_org": "entreprise|faction|gouvernement|informel",
      "domaine": "IA infrastructures",
      "taille": "moyenne"
    }
    
    OBJET: {
      "type_objet": "outil|vetement|nourriture|document|electronique|mobilier",
      "valeur": 50,
      "etat": "neuf|bon|use|abime|casse"
    }
    
    ARC_NARRATIF: {
      "type_arc": "travail|personnel|romance|exploration|mystere|social",
      "description": "...",
      "progression": 0, -- 0-100
      "obstacles": ["..."]
    }
  */
  
  -- Statut de l'entité
  confirme BOOLEAN DEFAULT true, -- false = mentionné mais pas encore rencontré/vérifié
  
  -- Cycle de vie
  cycle_creation INTEGER NOT NULL DEFAULT 1,
  cycle_disparition INTEGER, -- NULL = existe toujours
  raison_disparition TEXT, -- "mort", "détruit", "parti", "vendu"...
  
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  
  UNIQUE(partie_id, type, nom)
);

CREATE INDEX idx_kg_entites_partie ON kg_entites(partie_id);
CREATE INDEX idx_kg_entites_type ON kg_entites(partie_id, type);
CREATE INDEX idx_kg_entites_nom ON kg_entites(partie_id, nom);
CREATE INDEX idx_kg_entites_alias ON kg_entites USING GIN(alias);
CREATE INDEX idx_kg_entites_props ON kg_entites USING GIN(proprietes);
CREATE INDEX idx_kg_entites_actives ON kg_entites(partie_id) 
  WHERE cycle_disparition IS NULL;

-- ============================================================================
-- RELATIONS (Arêtes du graphe)
-- ============================================================================

CREATE TABLE kg_relations (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  partie_id UUID NOT NULL REFERENCES parties(id) ON DELETE CASCADE,
  
  -- Relation : source --[type]--> cible
  source_id UUID NOT NULL REFERENCES kg_entites(id) ON DELETE CASCADE,
  cible_id UUID NOT NULL REFERENCES kg_entites(id) ON DELETE CASCADE,
  type_relation VARCHAR(100) NOT NULL,
  /*
    PERSONNAGE <-> LIEU:
      - habite, travaille_a, frequente, a_visite, evite
    
    PERSONNAGE <-> PERSONNAGE:
      - connait (+ niveau 0-10, etape_romantique 0-6)
      - ami_de, famille_de, collegue_de, superieur_de, subordonne_de
      - en_couple_avec, ex_de, interesse_par
      - rival_de, ennemi_de, mefiant_envers
      - a_aide, doit_service_a, a_promis_a
    
    PERSONNAGE <-> ORGANISATION:
      - employe_de, membre_de, dirige, a_quitte, client_de
    
    PERSONNAGE <-> OBJET:
      - possede, veut, a_perdu, a_prete_a, a_emprunte_a
    
    PERSONNAGE <-> ARC:
      - implique_dans
    
    LIEU <-> LIEU:
      - situe_dans (hiérarchie)
      - connecte_a, proche_de, vue_sur
    
    LIEU <-> ORGANISATION:
      - appartient_a, siege_de
    
    ORGANISATION <-> ORGANISATION:
      - partenaire_de, concurrent_de, filiale_de
    
    IA <-> PROTAGONISTE:
      - assiste
  */
  
  -- Propriétés de la relation (JSONB)
  proprietes JSONB DEFAULT '{}',
  /*
    connait: { 
      "niveau": 2,           -- 0-10
      "etape_romantique": 1, -- 0-6 (si applicable)
      "contexte": "travail"
    }
    possede: { "quantite": 3, "depuis_cycle": 2 }
    employe_de: { "poste": "serveuse", "horaires": "soir" }
    doit_service_a: { "quoi": "lui a sauvé la mise", "importance": 3 }
    a_visite: { "cycles": [1, 3, 5] }
  */
  
  -- Temporalité
  cycle_debut INTEGER NOT NULL,
  cycle_fin INTEGER, -- NULL = toujours actif
  raison_fin TEXT, -- "rupture", "licenciement", "remboursé", "vendu"...
  
  -- Épistémologie (ce que Valentin sait)
  certitude VARCHAR(20) DEFAULT 'certain', 
  -- 'certain' : Valentin sait et c'est vrai
  -- 'croit' : Valentin croit mais c'est peut-être faux
  -- 'soupconne' : Valentin soupçonne sans preuve
  -- 'rumeur' : Valentin a entendu dire
  -- NULL : Valentin ne sait pas (hors-champ)
  
  verite BOOLEAN DEFAULT true,
  -- true : C'est vrai dans le monde
  -- false : C'est faux dans le monde
  -- NULL : Inconnu/indéterminé
  
  source_info VARCHAR(255), -- "vu", "entendu de X", "déduit"...
  
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  
  UNIQUE(partie_id, source_id, cible_id, type_relation, cycle_debut)
);

CREATE INDEX idx_kg_relations_partie ON kg_relations(partie_id);
CREATE INDEX idx_kg_relations_source ON kg_relations(source_id);
CREATE INDEX idx_kg_relations_cible ON kg_relations(cible_id);
CREATE INDEX idx_kg_relations_type ON kg_relations(partie_id, type_relation);
CREATE INDEX idx_kg_relations_actives ON kg_relations(partie_id) 
  WHERE cycle_fin IS NULL;

-- ============================================================================
-- ÉVÉNEMENTS (Nœuds spéciaux : ce qui s'est passé ou va se passer)
-- ============================================================================

CREATE TABLE kg_evenements (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  partie_id UUID NOT NULL REFERENCES parties(id) ON DELETE CASCADE,
  
  -- Classification
  type VARCHAR(50) NOT NULL,
  /*
    - 'passe' : événement qui s'est produit
    - 'planifie' : événement prévu (RDV, deadline)
    - 'recurrent' : événement qui se répète (loyer, réunion hebdo)
  */
  
  categorie VARCHAR(50),
  /*
    - 'social' : rencontre, conversation, conflit
    - 'travail' : réunion, deadline, promotion, problème
    - 'transaction' : achat, vente, paiement
    - 'deplacement' : arrivée, départ
    - 'decouverte' : révélation, apprentissage
    - 'incident' : accident, panne, conflit
    - 'station' : événement public, maintenance, alerte
  */
  
  -- Description
  titre VARCHAR(255) NOT NULL,
  description TEXT,
  
  -- Quand
  cycle INTEGER NOT NULL,
  heure VARCHAR(10), -- "14h30"
  
  -- Pour les récurrents
  recurrence JSONB, -- { "frequence": "mensuel", "prochain_cycle": 30 }
  
  -- Où (optionnel)
  lieu_id UUID REFERENCES kg_entites(id) ON DELETE SET NULL,
  
  -- Impact financier (pour transactions)
  montant INTEGER, -- positif = gain, négatif = dépense
  
  -- État (pour planifiés)
  realise BOOLEAN DEFAULT false,
  annule BOOLEAN DEFAULT false,
  raison_annulation TEXT,
  
  -- Épistémologie
  certitude VARCHAR(20) DEFAULT 'certain',
  verite BOOLEAN DEFAULT true,
  
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_kg_evenements_partie ON kg_evenements(partie_id);
CREATE INDEX idx_kg_evenements_cycle ON kg_evenements(partie_id, cycle);
CREATE INDEX idx_kg_evenements_type ON kg_evenements(partie_id, type);
CREATE INDEX idx_kg_evenements_planifies ON kg_evenements(partie_id, cycle) 
  WHERE type IN ('planifie', 'recurrent') AND realise = false AND annule = false;

-- Participants aux événements (many-to-many)
CREATE TABLE kg_evenement_participants (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  evenement_id UUID NOT NULL REFERENCES kg_evenements(id) ON DELETE CASCADE,
  entite_id UUID NOT NULL REFERENCES kg_entites(id) ON DELETE CASCADE,
  role VARCHAR(100), -- "initiateur", "participant", "temoin", "victime", "beneficiaire"
  
  UNIQUE(evenement_id, entite_id)
);

CREATE INDEX idx_kg_ev_part_event ON kg_evenement_participants(evenement_id);
CREATE INDEX idx_kg_ev_part_entite ON kg_evenement_participants(entite_id);

-- ============================================================================
-- ÉTATS TEMPORELS (Propriétés qui changent dans le temps)
-- ============================================================================

CREATE TABLE kg_etats (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  partie_id UUID NOT NULL REFERENCES parties(id) ON DELETE CASCADE,
  
  -- Quelle entité
  entite_id UUID NOT NULL REFERENCES kg_entites(id) ON DELETE CASCADE,
  
  -- Quel attribut
  attribut VARCHAR(100) NOT NULL,
  /*
    PROTAGONISTE:
      - energie (1-5)
      - moral (1-5)
      - sante (1-5)
      - credits (nombre)
      - humeur (texte)
      - localisation (lieu actuel)
    
    PERSONNAGE:
      - disposition (humeur envers Valentin)
      - stat_social (1-5)
      - stat_travail (1-5)
      - stat_sante (1-5)
      - humeur (état général)
      - localisation
    
    LIEU:
      - etat (ouvert, fermé, en_travaux, bondé, vide)
      - ambiance (calme, agité, dangereux)
    
    OBJET:
      - etat (neuf, bon, usé, abîmé, cassé)
    
    ARC_NARRATIF:
      - etat (actif, en_pause, termine, abandonne)
      - progression (0-100)
  */
  
  valeur TEXT NOT NULL,
  details JSONB, -- Infos supplémentaires
  
  -- Validité temporelle
  cycle_debut INTEGER NOT NULL,
  cycle_fin INTEGER, -- NULL = toujours actuel
  
  -- Épistémologie
  certitude VARCHAR(20) DEFAULT 'certain',
  verite BOOLEAN DEFAULT true,
  
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_kg_etats_partie ON kg_etats(partie_id);
CREATE INDEX idx_kg_etats_entite ON kg_etats(entite_id);
CREATE INDEX idx_kg_etats_attribut ON kg_etats(entite_id, attribut);
CREATE INDEX idx_kg_etats_actifs ON kg_etats(entite_id) WHERE cycle_fin IS NULL;

-- ============================================================================
-- MÉTRIQUES EXTRACTION (pour monitoring)
-- ============================================================================

CREATE TABLE kg_extraction_logs (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  partie_id UUID NOT NULL REFERENCES parties(id) ON DELETE CASCADE,
  
  cycle INTEGER NOT NULL,
  scene_id UUID REFERENCES scenes(id) ON DELETE SET NULL,
  
  -- Timing
  duree_ms INTEGER, -- Temps d'extraction Haiku
  
  -- Résultats
  nb_operations INTEGER DEFAULT 0,
  nb_entites_creees INTEGER DEFAULT 0,
  nb_relations_creees INTEGER DEFAULT 0,
  nb_evenements_crees INTEGER DEFAULT 0,
  nb_etats_modifies INTEGER DEFAULT 0,
  
  -- Problèmes
  nb_contradictions INTEGER DEFAULT 0,
  nb_entites_non_resolues INTEGER DEFAULT 0,
  nb_operations_invalides INTEGER DEFAULT 0,
  
  -- Détails
  contradictions JSONB, -- Liste des contradictions détectées
  erreurs JSONB, -- Erreurs rencontrées
  
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_kg_logs_partie ON kg_extraction_logs(partie_id);
CREATE INDEX idx_kg_logs_cycle ON kg_extraction_logs(partie_id, cycle);

-- ============================================================================
-- FONCTIONS UTILITAIRES
-- ============================================================================

-- Trouver une entité par nom ou alias
CREATE OR REPLACE FUNCTION kg_trouver_entite(
  p_partie_id UUID,
  p_nom TEXT,
  p_type VARCHAR DEFAULT NULL
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
      LOWER(nom) LIKE v_nom_lower || ' %'  -- "Justine" match "Justine Lépicier"
      OR LOWER(nom) LIKE '% ' || v_nom_lower -- "Lépicier" match "Justine Lépicier"
    )
  LIMIT 1;
  
  RETURN v_id; -- NULL si pas trouvé
END;
$$ LANGUAGE plpgsql;

-- Créer ou mettre à jour une entité
CREATE OR REPLACE FUNCTION kg_upsert_entite(
  p_partie_id UUID,
  p_type VARCHAR,
  p_nom VARCHAR,
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
  -- Chercher entité existante
  v_id := kg_trouver_entite(p_partie_id, p_nom, p_type);
  
  IF v_id IS NOT NULL THEN
    -- Récupérer données existantes
    SELECT alias, proprietes INTO v_existing_alias, v_existing_props
    FROM kg_entites WHERE id = v_id;
    
    -- Mise à jour : fusionner proprietes et alias
    UPDATE kg_entites SET
      proprietes = v_existing_props || p_proprietes,
      alias = ARRAY(SELECT DISTINCT unnest(v_existing_alias || p_alias)),
      confirme = GREATEST(confirme::int, p_confirme::int)::boolean,
      updated_at = NOW()
    WHERE id = v_id;
    
    RETURN v_id;
  ELSE
    -- Création
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
  p_type VARCHAR,
  p_proprietes JSONB DEFAULT '{}',
  p_cycle INTEGER DEFAULT 1,
  p_certitude VARCHAR DEFAULT 'certain',
  p_verite BOOLEAN DEFAULT true,
  p_source_info VARCHAR DEFAULT NULL
)
RETURNS UUID AS $$
DECLARE
  v_id UUID;
  v_existing_props JSONB;
BEGIN
  -- Vérifier si relation active existe
  SELECT id, proprietes INTO v_id, v_existing_props
  FROM kg_relations
  WHERE partie_id = p_partie_id
    AND source_id = p_source_id
    AND cible_id = p_cible_id
    AND type_relation = p_type
    AND cycle_fin IS NULL;
  
  IF v_id IS NOT NULL THEN
    -- Mettre à jour (merge propriétés)
    UPDATE kg_relations SET
      proprietes = v_existing_props || p_proprietes,
      certitude = p_certitude,
      verite = p_verite,
      source_info = COALESCE(p_source_info, source_info)
    WHERE id = v_id;
    
    RETURN v_id;
  ELSE
    -- Créer
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
  p_type VARCHAR,
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

-- Mettre à jour un état (termine l'ancien automatiquement)
CREATE OR REPLACE FUNCTION kg_set_etat(
  p_partie_id UUID,
  p_entite_id UUID,
  p_attribut VARCHAR,
  p_valeur TEXT,
  p_cycle INTEGER,
  p_details JSONB DEFAULT NULL,
  p_certitude VARCHAR DEFAULT 'certain',
  p_verite BOOLEAN DEFAULT true
)
RETURNS UUID AS $$
DECLARE
  v_id UUID;
  v_old_valeur TEXT;
BEGIN
  -- Vérifier si la valeur change vraiment
  SELECT valeur INTO v_old_valeur
  FROM kg_etats
  WHERE entite_id = p_entite_id
    AND attribut = p_attribut
    AND cycle_fin IS NULL;
  
  -- Si même valeur, ne rien faire
  IF v_old_valeur = p_valeur THEN
    RETURN NULL;
  END IF;
  
  -- Terminer l'état précédent
  UPDATE kg_etats SET cycle_fin = p_cycle
  WHERE entite_id = p_entite_id
    AND attribut = p_attribut
    AND cycle_fin IS NULL;
  
  -- Créer le nouvel état
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

-- ============================================================================
-- VUES UTILES
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

-- Événements à venir
CREATE OR REPLACE VIEW kg_v_evenements_a_venir AS
SELECT 
  ev.*,
  l.nom AS lieu_nom,
  ARRAY_AGG(DISTINCT ent.nom) FILTER (WHERE ent.nom IS NOT NULL) AS participants
FROM kg_evenements ev
LEFT JOIN kg_entites l ON ev.lieu_id = l.id
LEFT JOIN kg_evenement_participants ep ON ev.id = ep.evenement_id
LEFT JOIN kg_entites ent ON ep.entite_id = ent.id
WHERE ev.type IN ('planifie', 'recurrent')
  AND ev.realise = false
  AND ev.annule = false
GROUP BY ev.id, l.nom;

-- Inventaire de Valentin (relations POSSEDE actives)
CREATE OR REPLACE VIEW kg_v_inventaire AS
SELECT 
  r.partie_id,
  e_objet.id AS objet_id,
  e_objet.nom AS objet_nom,
  e_objet.proprietes AS objet_props,
  r.proprietes AS relation_props,
  COALESCE((r.proprietes->>'quantite')::int, 1) AS quantite
FROM kg_relations r
JOIN kg_entites e_val ON r.source_id = e_val.id AND e_val.type = 'protagoniste'
JOIN kg_entites e_objet ON r.cible_id = e_objet.id AND e_objet.type = 'objet'
WHERE r.type_relation = 'possede'
  AND r.cycle_fin IS NULL
  AND e_objet.cycle_disparition IS NULL;
