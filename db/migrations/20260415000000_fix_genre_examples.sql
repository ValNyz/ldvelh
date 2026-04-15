-- migrate:up
-- Fix genre world_gen_example: add missing fields (protagonist, personal_assistant, inventory, initial_relations)
-- These fields were missing, causing weaker LLMs (Mistral) to skip them entirely.

UPDATE genres SET world_gen_example = '{
  "generation_seed_words": ["rouille", "reconversion", "isolement"],
  "world": {
    "name": "Escale Méridienne",
    "description": "Ancienne station minière reconvertie. Infrastructure vieillissante.",
    "atmosphere": "Station industrielle usée, indifférence ambiante",
    "sectors": ["Quai Central", "Quartier Ouvrier"],
    "founding_cycle": -4500
  },
  "protagonist": {
    "name": "Valentin",
    "origin": "Cité-Dôme de Vega III",
    "departure_reason": "fresh_start",
    "backstory": "Développeur compétent mais fatigué. Burnout après huit ans.",
    "occupation": "développeur IA senior",
    "credits": 1650,
    "employer_ref": "Services Techniques Méridiens",
    "residence_ref": "Appartement 4-12",
    "skills": [{"name": "architecture_systemes", "level": 4}, {"name": "programmation_ia", "level": 3}]
  },
  "personal_assistant": {
    "name": "Célimène",
    "voice": "voix rauque, débit lent",
    "traits": ["sarcastique", "observatrice"],
    "substrate": "personal_device",
    "quirk": "Note les contradictions sans les commenter"
  },
  "locations": [
    {
      "name": "Terminal Quai 7",
      "location_type": "terminal",
      "sector": "Quai Central",
      "description": "Hall bruyant aux plafonds tachés.",
      "atmosphere": "transit impersonnel",
      "accessible": true
    },
    {
      "name": "Appartement 4-12",
      "parent_location_ref": "Bloc Tournesol",
      "location_type": "apartment",
      "sector": "Quartier Ouvrier",
      "description": "28m², murs fins, vue sur conduit d''aération.",
      "atmosphere": "exigu et impersonnel",
      "accessible": true
    }
  ],
  "characters": [
    {
      "name": "Justine Lépicier",
      "species": "human",
      "gender": "female",
      "pronouns": "elle",
      "age": 41,
      "occupation": "technicienne maintenance",
      "description": "Visage fatigué, mains calleuses. Parle peu.",
      "traits": ["pragmatique", "méfiante", "compétente"],
      "known_by_protagonist": false,
      "unknown_name": "Femme en bleu de travail",
      "workplace_ref": "Terminal Quai 7",
      "residence_ref": "Appartement 4-12"
    }
  ],
  "organizations": [
    {
      "name": "Services Techniques Méridiens",
      "org_type": "département",
      "domain": "maintenance",
      "size": "medium",
      "is_employer": true,
      "description": "Gère l''infrastructure vieillissante."
    }
  ],
  "inventory": [
    {"name": "Terminal personnel", "category": "tech", "description": "Modèle standard usé", "transportable": true, "stackable": false, "base_value": 300, "quantity": 1},
    {"name": "Valise cabine", "category": "baggage", "description": "Plastique rayé", "transportable": true, "stackable": false, "base_value": 40, "quantity": 1}
  ],
  "narrative_arcs": [
    {
      "title": "Intégration difficile",
      "domain": "professional",
      "description": "Le protagoniste cherche sa place dans un monde qui ne l''attendait pas.",
      "intensity": 3,
      "involved_entities": ["Justine Lépicier"]
    }
  ],
  "initial_relations": [
    {"source_ref": "Valentin", "target_ref": "Appartement 4-12", "relation_type": "lives_at", "known_by_protagonist": true},
    {"source_ref": "Valentin", "target_ref": "Services Techniques Méridiens", "relation_type": "employed_by", "known_by_protagonist": true},
    {"source_ref": "Justine Lépicier", "target_ref": "Terminal Quai 7", "relation_type": "works_at", "known_by_protagonist": false},
    {"source_ref": "Justine Lépicier", "target_ref": "Appartement 4-12", "relation_type": "lives_at", "known_by_protagonist": false},
    {"source_ref": "Appartement 4-12", "target_ref": "Bloc Tournesol", "relation_type": "located_in", "known_by_protagonist": false}
  ]
}' WHERE slug = 'sci_fi';

UPDATE genres SET world_gen_example = '{
  "generation_seed_words": ["famine", "trahison", "murailles"],
  "world": {
    "name": "Havrepierre",
    "description": "Cité fortifiée sur un plateau venteux. Murailles grises, rues boueuses.",
    "atmosphere": "Méfiance ambiante, survie quotidienne",
    "sectors": ["Basse-Ville", "Quartier des Forges"],
    "founding_cycle": -5000
  },
  "protagonist": {
    "name": "Valentin",
    "origin": "Village de Crèvecoeur",
    "departure_reason": "flight",
    "backstory": "A fui son village après un incendie suspect. N''a rien emporté.",
    "occupation": "sans emploi",
    "credits": 350,
    "residence_ref": "Chambre au-dessus de la forge",
    "skills": [{"name": "survie", "level": 3}, {"name": "observation", "level": 2}]
  },
  "personal_assistant": {
    "name": "Vieille Boussole",
    "voice": "aucune — objet inerte",
    "traits": ["fiable"],
    "substrate": "objet personnel",
    "quirk": "L''aiguille tremble parfois sans raison"
  },
  "locations": [
    {
      "name": "La Couronne Fendue",
      "location_type": "taverne",
      "sector": "Basse-Ville",
      "description": "Salle enfumée, poutres basses. Bière tiède.",
      "atmosphere": "bruyant et méfiant",
      "accessible": true
    },
    {
      "name": "Chambre au-dessus de la forge",
      "parent_location_ref": "Forge de Marten",
      "location_type": "lodging",
      "sector": "Quartier des Forges",
      "description": "Paillasse, mur de pierre suintant. Chaleur de la forge en dessous.",
      "atmosphere": "étouffant mais chaud",
      "accessible": true
    }
  ],
  "characters": [
    {
      "name": "Marten le Rouge",
      "species": "human",
      "gender": "male",
      "pronouns": "il",
      "age": 55,
      "occupation": "forgeron",
      "description": "Bras énormes, visage brûlé. Parle fort, rit peu.",
      "traits": ["bourru", "honnête", "protecteur"],
      "known_by_protagonist": false,
      "unknown_name": "Le forgeron rougeaud",
      "workplace_ref": "La Couronne Fendue",
      "residence_ref": "Chambre au-dessus de la forge"
    }
  ],
  "organizations": [
    {
      "name": "Guilde des Forgerons",
      "org_type": "guilde",
      "domain": "artisanat",
      "size": "small",
      "is_employer": false,
      "description": "Contrôle le travail du métal dans la cité."
    }
  ],
  "inventory": [
    {"name": "Couteau rouillé", "category": "weapon", "description": "Lame ébréchée mais fonctionnelle", "transportable": true, "stackable": false, "base_value": 15, "quantity": 1},
    {"name": "Bourse en cuir", "category": "container", "description": "Quelques pièces dedans", "transportable": true, "stackable": false, "base_value": 5, "quantity": 1}
  ],
  "narrative_arcs": [
    {
      "title": "Trouver un toit",
      "domain": "personal",
      "description": "Le protagoniste doit se loger avant l''hiver.",
      "intensity": 4,
      "involved_entities": ["Marten le Rouge"]
    }
  ],
  "initial_relations": [
    {"source_ref": "Valentin", "target_ref": "Chambre au-dessus de la forge", "relation_type": "lives_at", "known_by_protagonist": true},
    {"source_ref": "Marten le Rouge", "target_ref": "La Couronne Fendue", "relation_type": "works_at", "known_by_protagonist": false},
    {"source_ref": "Marten le Rouge", "target_ref": "Chambre au-dessus de la forge", "relation_type": "lives_at", "known_by_protagonist": false},
    {"source_ref": "Chambre au-dessus de la forge", "target_ref": "Forge de Marten", "relation_type": "located_in", "known_by_protagonist": false},
    {"source_ref": "Guilde des Forgerons", "target_ref": "La Couronne Fendue", "relation_type": "located_in", "known_by_protagonist": false}
  ]
}' WHERE slug = 'dark_fantasy';

UPDATE genres SET world_gen_example = '{
  "generation_seed_words": ["brouillard", "archives", "disparitions"],
  "world": {
    "name": "Port-Sable",
    "description": "Ville côtière brumeuse. Architecture victorienne décrépite.",
    "atmosphere": "Malaise permanent, secrets enfouis",
    "sectors": ["Vieux Port", "Quartier Universitaire"],
    "founding_cycle": -6000
  },
  "protagonist": {
    "name": "Valentin",
    "origin": "Paris",
    "departure_reason": "opportunity",
    "backstory": "Archiviste envoyé pour cataloguer une collection privée. Curieux mais naïf.",
    "occupation": "archiviste",
    "credits": 2200,
    "employer_ref": "Société Historique de Port-Sable",
    "residence_ref": "Pension du Goéland",
    "skills": [{"name": "recherche", "level": 4}, {"name": "langues_anciennes", "level": 3}]
  },
  "personal_assistant": {
    "name": "Carnet relié",
    "voice": "aucune — objet inerte",
    "traits": ["fiable"],
    "substrate": "objet personnel",
    "quirk": "Certaines pages semblent avoir été arrachées avant l''achat"
  },
  "locations": [
    {
      "name": "Bibliothèque Ashmore",
      "location_type": "bibliothèque",
      "sector": "Quartier Universitaire",
      "description": "Rayonnages infinis, odeur de moisi. Certaines sections sont condamnées.",
      "atmosphere": "silence oppressant",
      "accessible": true
    },
    {
      "name": "Pension du Goéland",
      "location_type": "pension",
      "sector": "Vieux Port",
      "description": "Chambres humides, papier peint décollé.",
      "atmosphere": "inconfortable et surveillé",
      "accessible": true
    }
  ],
  "characters": [
    {
      "name": "Dr. Elise Marsh",
      "species": "human",
      "gender": "female",
      "pronouns": "elle",
      "age": 62,
      "occupation": "archiviste municipale",
      "description": "Lunettes épaisses, mains tremblantes. Évite certains sujets.",
      "traits": ["nerveuse", "érudite", "évasive"],
      "known_by_protagonist": false,
      "unknown_name": "La vieille dame de la bibliothèque",
      "workplace_ref": "Bibliothèque Ashmore",
      "residence_ref": "Pension du Goéland"
    }
  ],
  "organizations": [
    {
      "name": "Société Historique de Port-Sable",
      "org_type": "association",
      "domain": "recherche historique",
      "size": "small",
      "is_employer": true,
      "description": "Gardiens autoproclamés de l''histoire locale. Très sélectifs."
    }
  ],
  "inventory": [
    {"name": "Loupe de poche", "category": "tool", "description": "Verre légèrement rayé", "transportable": true, "stackable": false, "base_value": 80, "quantity": 1},
    {"name": "Valise de voyage", "category": "baggage", "description": "Cuir patiné, étiquettes de voyage", "transportable": true, "stackable": false, "base_value": 60, "quantity": 1}
  ],
  "narrative_arcs": [
    {
      "title": "Les archives manquantes",
      "domain": "professional",
      "description": "Des documents importants ont disparu. Personne ne veut en parler.",
      "intensity": 3,
      "involved_entities": ["Dr. Elise Marsh"]
    }
  ],
  "initial_relations": [
    {"source_ref": "Valentin", "target_ref": "Pension du Goéland", "relation_type": "lives_at", "known_by_protagonist": true},
    {"source_ref": "Valentin", "target_ref": "Société Historique de Port-Sable", "relation_type": "employed_by", "known_by_protagonist": true},
    {"source_ref": "Dr. Elise Marsh", "target_ref": "Bibliothèque Ashmore", "relation_type": "works_at", "known_by_protagonist": false},
    {"source_ref": "Dr. Elise Marsh", "target_ref": "Pension du Goéland", "relation_type": "lives_at", "known_by_protagonist": false},
    {"source_ref": "Société Historique de Port-Sable", "target_ref": "Bibliothèque Ashmore", "relation_type": "located_in", "known_by_protagonist": false}
  ]
}' WHERE slug = 'cosmic_horror';

UPDATE genres SET world_gen_example = '{
  "generation_seed_words": ["dette", "implants", "blackout"],
  "world": {
    "name": "Néo-Shinjuku",
    "description": "Mégalopole verticale. Tours corporatives au-dessus, bidonvilles en dessous.",
    "atmosphere": "Néon, pluie, inégalité",
    "sectors": ["Sous-niveaux", "District Corporate"],
    "founding_cycle": -3000
  },
  "protagonist": {
    "name": "Valentin",
    "origin": "Ancienne Europe",
    "departure_reason": "broke",
    "backstory": "Expulsé après faillite. Implants de base, dettes énormes.",
    "occupation": "technicien freelance",
    "credits": 180,
    "residence_ref": "Capsule 7-B",
    "skills": [{"name": "hacking", "level": 3}, {"name": "electronique", "level": 3}]
  },
  "personal_assistant": {
    "name": "GHOST",
    "voice": "synthétique, phrases courtes",
    "traits": ["minimaliste", "paranoïaque"],
    "substrate": "implant neural",
    "quirk": "Coupe la connexion sans prévenir quand il détecte un scan"
  },
  "locations": [
    {
      "name": "Le Byte Bar",
      "location_type": "bar",
      "sector": "Sous-niveaux",
      "description": "Comptoir en aluminium, écrans partout. Clientèle louche.",
      "atmosphere": "enfumé et connecté",
      "accessible": true
    },
    {
      "name": "Capsule 7-B",
      "parent_location_ref": "Bloc Capsules Akira",
      "location_type": "appartement-capsule",
      "sector": "Sous-niveaux",
      "description": "2m x 1m x 1m. Écran intégré, prise de recharge. Rien d''autre.",
      "atmosphere": "claustrophobe mais connecté",
      "accessible": true
    }
  ],
  "characters": [
    {
      "name": "Jin",
      "species": "human",
      "gender": "non-binary",
      "pronouns": "iel",
      "age": 28,
      "occupation": "fixeur",
      "description": "Implants visibles aux tempes, veste en cuir synthétique.",
      "traits": ["pragmatique", "connecté", "méfiant"],
      "known_by_protagonist": false,
      "unknown_name": "La personne aux implants",
      "workplace_ref": "Le Byte Bar",
      "residence_ref": "Capsule 7-B"
    }
  ],
  "organizations": [
    {
      "name": "Nexion Corp",
      "org_type": "corporation",
      "domain": "neurotechnologie",
      "size": "large",
      "is_employer": false,
      "description": "Fabrique 70% des implants neuraux du marché. Omniprésente."
    }
  ],
  "inventory": [
    {"name": "Deck de hacking", "category": "tech", "description": "Modèle bas de gamme, modifié", "transportable": true, "stackable": false, "base_value": 450, "quantity": 1},
    {"name": "Stimulant neural", "category": "consumable", "description": "Boost de 30min, crash garanti", "transportable": true, "stackable": true, "base_value": 25, "quantity": 3}
  ],
  "narrative_arcs": [
    {
      "title": "La dette",
      "domain": "financial",
      "description": "Le protagoniste doit 15000 crédits à un prêteur peu patient.",
      "intensity": 4,
      "involved_entities": []
    }
  ],
  "initial_relations": [
    {"source_ref": "Valentin", "target_ref": "Capsule 7-B", "relation_type": "lives_at", "known_by_protagonist": true},
    {"source_ref": "Jin", "target_ref": "Le Byte Bar", "relation_type": "works_at", "known_by_protagonist": false},
    {"source_ref": "Jin", "target_ref": "Capsule 7-B", "relation_type": "lives_at", "known_by_protagonist": false},
    {"source_ref": "Capsule 7-B", "target_ref": "Bloc Capsules Akira", "relation_type": "located_in", "known_by_protagonist": false},
    {"source_ref": "Nexion Corp", "target_ref": "Le Byte Bar", "relation_type": "located_in", "known_by_protagonist": false}
  ]
}' WHERE slug = 'cyberpunk';

-- migrate:down
-- Revert to old shorter examples (without protagonist/assistant/inventory/relations)
-- Not worth maintaining rollback data for this — the old examples were simply incomplete.
