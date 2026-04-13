-- migrate:up

-- Genre system: configurable world genres with tone, vocabulary, and examples
CREATE TABLE genres (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    slug VARCHAR(30) NOT NULL,
    label VARCHAR(100) NOT NULL,
    is_preset BOOLEAN DEFAULT false,

    -- Tone & style
    tone_style TEXT NOT NULL,
    friction_flavor TEXT NOT NULL,
    atmosphere_guidelines TEXT,

    -- Vocabulary
    world_type VARCHAR(100),
    location_types TEXT[],
    npc_archetypes TEXT[],

    -- Arrival
    arrival_prompt TEXT,

    -- World gen example (compact JSON)
    world_gen_example TEXT,

    -- Constraints
    forbidden_ai_names TEXT[],

    created_at TIMESTAMPTZ DEFAULT now(),

    UNIQUE(slug, user_id)
);

CREATE INDEX idx_genres_presets ON genres(is_preset) WHERE is_preset = true;
CREATE INDEX idx_genres_user ON genres(user_id) WHERE user_id IS NOT NULL;

-- Link games to genres
ALTER TABLE games ADD COLUMN genre_id UUID REFERENCES genres(id);

-- ============================================================================
-- SEED PRESET GENRES
-- ============================================================================

INSERT INTO genres (slug, label, is_preset, tone_style, friction_flavor, atmosphere_guidelines, world_type, location_types, npc_archetypes, arrival_prompt, forbidden_ai_names, world_gen_example) VALUES

-- SCI-FI
('sci_fi', 'Science-Fiction', true,
$$Becky Chambers pour l'attention aux détails du quotidien. Sans la chaleur systématique.

- Quotidien banal : les petits moments, souvent chiants ou vides
- Personnages occupés : chacun a ses problèmes, le protagoniste n'est pas leur priorité
- Diversité banale : espèces, genres, cultures — c'est juste normal
- Mélancolie : l'ennui, la solitude, les longueurs font partie du jeu
- Monde indifférent : personne n'attendait le protagoniste
- Conflits sans méchants : les gens sont juste fatigués, stressés, ou incompatibles$$,

$$Bureaucratie, pannes techniques, files d'attente, systèmes en maintenance.
Les PNJ ont leurs propres deadlines et ne s'arrêtent pas pour le protagoniste.
L'administration est lente, les formulaires nombreux, les droits d'accès limités.$$,

$$Descriptions sensorielles : air recyclé, bourdonnement des systèmes, éclairage artificiel.
Mélange de high-tech usé et de bricolage. Odeurs de café synthétique et de métal chaud.
Pas de grandeur spatiale — juste le quotidien dans un tube pressurisé.$$,

'station spatiale',
ARRAY['terminal', 'quartier résidentiel', 'zone commerciale', 'dock', 'serre', 'laboratoire', 'cafétéria', 'bureau'],
ARRAY['technicien', 'docker', 'administrateur', 'médecin', 'commerçant', 'ingénieur', 'chercheur'],
'Tu viens d''arriver sur {world_name}. L''air recyclé te pique les narines. Autour de toi, des voyageurs fatigués traînent leurs bagages.',
ARRAY['Aria', 'Nova', 'Luna', 'Stella', 'Aurora', 'Cortana', 'Alexa', 'Siri', 'Echo', 'Iris'],
$${
  "generation_seed_words": ["rouille", "reconversion", "isolement"],
  "world": {
    "name": "Escale Méridienne",
    "description": "Ancienne station minière reconvertie. Infrastructure vieillissante.",
    "atmosphere": "Station industrielle usée, indifférence ambiante",
    "sectors": ["Quai Central", "Quartier Ouvrier"],
    "founding_cycle": -4500
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
      "description": "28m², murs fins, vue sur conduit d'aération.",
      "atmosphere": "exigu et impersonnel",
      "accessible": true
    }
  ],
  "characters": [
    {
      "name": "Justine Lépicier",
      "species": "human",
      "gender": "female",
      "age": 41,
      "occupation": "technicienne maintenance",
      "description": "Visage fatigué, mains calleuses. Parle peu.",
      "traits": ["pragmatique", "méfiante", "compétente"],
      "known_by_protagonist": false,
      "unknown_name": "Femme en bleu de travail"
    }
  ],
  "organizations": [
    {
      "name": "Services Techniques Méridiens",
      "org_type": "département",
      "domain": "maintenance",
      "description": "Gère l'infrastructure vieillissante."
    }
  ],
  "narrative_arcs": [
    {
      "title": "Intégration difficile",
      "domain": "professional",
      "description": "Le protagoniste cherche sa place dans un monde qui ne l'attendait pas.",
      "intensity": 3,
      "involved_entities": []
    }
  ]
}$$),

-- DARK FANTASY
('dark_fantasy', 'Dark Fantasy', true,
$$Joe Abercrombie pour le cynisme pragmatique. Le monde est dur, injuste, et personne ne viendra sauver personne.

- Quotidien brutal : la boue, le froid, la faim, la maladie
- Personnages abîmés : chacun porte ses cicatrices, physiques et morales
- Moralité grise : pas de héros, pas de méchants — juste des survivants
- Superstition : les gens croient aux signes, aux malédictions, aux esprits
- Monde indifférent : la nature est hostile, les puissants sont cruels
- Violence banalisée : la mort est commune, pas spectaculaire$$,

$$Disette, maladies, routes dangereuses, auberges surpeuplées.
Les PNJ ont peur des étrangers et protègent leurs ressources.
L'autorité est arbitraire, la justice achetable, les promesses rarement tenues.$$,

$$Descriptions sensorielles : fumée de bois, sueur, cuir mouillé, sang séché.
Lumière de bougies et de feux. Ombres partout. Architecture de pierre et de bois.
Pas de grandeur épique — juste la survie au jour le jour.$$,

'cité fortifiée',
ARRAY['taverne', 'forge', 'marché', 'temple', 'caserne', 'quartier pauvre', 'château', 'port'],
ARRAY['forgeron', 'aubergiste', 'soldat', 'prêtre', 'marchand', 'mendiant', 'noble', 'guérisseur'],
'Tu franchis les portes de {world_name}. L''odeur de fumée et de crottin te prend à la gorge. Des gardes te dévisagent sans bouger.',
ARRAY['Morgane', 'Excalibur', 'Gandalf', 'Elrond', 'Legolas', 'Galadriel'],
$${
  "generation_seed_words": ["famine", "trahison", "murailles"],
  "world": {
    "name": "Havrepierre",
    "description": "Cité fortifiée sur un plateau venteux. Murailles grises, rues boueuses.",
    "atmosphere": "Méfiance ambiante, survie quotidienne",
    "sectors": ["Basse-Ville", "Quartier des Forges"],
    "founding_cycle": -5000
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
      "age": 55,
      "occupation": "forgeron",
      "description": "Bras énormes, visage brûlé. Parle fort, rit peu.",
      "traits": ["bourru", "honnête", "protecteur"],
      "known_by_protagonist": false,
      "unknown_name": "Le forgeron rougeaud"
    }
  ],
  "organizations": [
    {
      "name": "Guilde des Forgerons",
      "org_type": "guilde",
      "domain": "artisanat",
      "description": "Contrôle le travail du métal dans la cité."
    }
  ],
  "narrative_arcs": [
    {
      "title": "Trouver un toit",
      "domain": "personal",
      "description": "Le protagoniste doit se loger avant l'hiver.",
      "intensity": 4,
      "involved_entities": []
    }
  ]
}$$),

-- COSMIC HORROR
('cosmic_horror', 'Horreur Cosmique', true,
$$Lovecraft pour l'incompréhensible, Ligotti pour le pessimisme quotidien. Le monde cache quelque chose de fondamentalement mauvais.

- Quotidien qui se fissure : tout semble normal jusqu'à ce que ça ne le soit plus
- Personnages nerveux : chacun sent que quelque chose ne va pas sans pouvoir le nommer
- Savoir dangereux : plus on comprend, plus on perd pied
- Isolation : personne ne croira le protagoniste, personne ne peut aider
- Monde hostile sous la surface : la réalité elle-même est suspecte
- Folie banalisée : les gens qui "savent" sont considérés comme fous$$,

$$Brouillard persistant, bruits inexpliqués, documents manquants, souvenirs contradictoires.
Les PNJ sont évasifs, changent de sujet, ou nient des évidences.
Les institutions cachent des choses, les archives sont incomplètes, les nuits sont trop longues.$$,

$$Descriptions sensorielles : humidité, moisissure, ozone, silence assourdissant.
Éclairage jaune ou absent. Géométrie presque correcte. Ombres qui ne correspondent pas.
Atmosphère de malaise permanent — pas de monstres, juste l'intuition que quelque chose regarde.$$,

'ville côtière isolée',
ARRAY['bibliothèque', 'phare', 'port', 'manoir', 'église', 'cave', 'laboratoire', 'asile'],
ARRAY['bibliothécaire', 'gardien de phare', 'pêcheur', 'professeur', 'prêtre', 'médecin', 'archiviste'],
'Tu descends du bus à {world_name}. Le brouillard est si épais que tu ne vois pas le bout de la rue. Personne ne t''attendait.',
ARRAY['Cthulhu', 'Nyarlathotep', 'Azathoth', 'Dagon'],
$${
  "generation_seed_words": ["brouillard", "archives", "disparitions"],
  "world": {
    "name": "Port-Sable",
    "description": "Ville côtière brumeuse. Architecture victorienne décrépite.",
    "atmosphere": "Malaise permanent, secrets enfouis",
    "sectors": ["Vieux Port", "Quartier Universitaire"],
    "founding_cycle": -6000
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
      "description": "Chambres humides, papier peint décollé. La propriétaire parle peu.",
      "atmosphere": "inconfortable et surveillé",
      "accessible": true
    }
  ],
  "characters": [
    {
      "name": "Dr. Elise Marsh",
      "species": "human",
      "gender": "female",
      "age": 62,
      "occupation": "archiviste municipale",
      "description": "Lunettes épaisses, mains tremblantes. Évite certains sujets.",
      "traits": ["nerveuse", "érudite", "évasive"],
      "known_by_protagonist": false,
      "unknown_name": "La vieille dame de la bibliothèque"
    }
  ],
  "organizations": [
    {
      "name": "Société Historique de Port-Sable",
      "org_type": "association",
      "domain": "recherche historique",
      "description": "Gardiens autoproclamés de l'histoire locale. Très sélectifs."
    }
  ],
  "narrative_arcs": [
    {
      "title": "Les archives manquantes",
      "domain": "professional",
      "description": "Des documents importants ont disparu. Personne ne veut en parler.",
      "intensity": 3,
      "involved_entities": []
    }
  ]
}$$),

-- CYBERPUNK
('cyberpunk', 'Cyberpunk', true,
$$William Gibson pour le détail technologique froid, Philip K. Dick pour la paranoïa identitaire. High tech, low life.

- Quotidien saturé : publicités holographiques, drones de livraison, implants omniprésents
- Personnages augmentés : tout le monde a des implants, c'est banal, pas spectaculaire
- Inégalité radicale : les corporations contrôlent tout, la rue survit comme elle peut
- Surveillance permanente : caméras, IA de surveillance, données vendues
- Monde cynique : l'argent est le seul langage universel
- Identité floue : entre avatars, implants et données, qui est vraiment qui$$,

$$Dettes, surveillance, pannes d'implants, coupures de réseau, loyers impayés.
Les PNJ sont méfiants car tout le monde espionne pour quelqu'un.
Les corporations font la loi, la police est privatisée, la justice n'existe pas pour les pauvres.$$,

$$Descriptions sensorielles : néons, pluie acide, odeur de plastique brûlé, bruit blanc des serveurs.
Contraste entre les tours de verre des corporations et les ruelles de béton.
Hologrammes défaillants, écrans partout, câbles qui pendent. Beau et sale à la fois.$$,

'mégalopole',
ARRAY['bar', 'marché noir', 'clinique', 'datacenter', 'appartement-capsule', 'entrepôt', 'corporation', 'arcade'],
ARRAY['hacker', 'fixeur', 'médecin de rue', 'corpo', 'dealer', 'mercenaire', 'technicien', 'coursier'],
'Tu sors du métro dans les sous-niveaux de {world_name}. Les néons clignotent, la pluie dégouline le long des murs de béton. Ton implant neural affiche 3% de batterie.',
ARRAY['Cortana', 'Alexa', 'Siri', 'HAL', 'Skynet', 'GLaDOS'],
$${
  "generation_seed_words": ["dette", "implants", "blackout"],
  "world": {
    "name": "Néo-Shinjuku",
    "description": "Mégalopole verticale. Tours corporatives au-dessus, bidonvilles en dessous.",
    "atmosphere": "Néon, pluie, inégalité",
    "sectors": ["Sous-niveaux", "District Corporate"],
    "founding_cycle": -3000
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
      "description": "2m x 1m x 1m. Écran intégré, prise de recharge. Rien d'autre.",
      "atmosphere": "claustrophobe mais connecté",
      "accessible": true
    }
  ],
  "characters": [
    {
      "name": "Jin",
      "species": "human",
      "gender": "non-binary",
      "age": 28,
      "occupation": "fixeur",
      "description": "Implants visibles aux tempes, veste en cuir synthétique. Regard calculateur.",
      "traits": ["pragmatique", "connecté", "méfiant"],
      "known_by_protagonist": false,
      "unknown_name": "La personne aux implants"
    }
  ],
  "organizations": [
    {
      "name": "Nexion Corp",
      "org_type": "corporation",
      "domain": "neurotechnologie",
      "description": "Fabrique 70% des implants neuraux du marché. Omniprésente."
    }
  ],
  "narrative_arcs": [
    {
      "title": "La dette",
      "domain": "financial",
      "description": "Le protagoniste doit 15000 crédits à un prêteur peu patient.",
      "intensity": 4,
      "involved_entities": []
    }
  ]
}$$);

-- migrate:down

ALTER TABLE games DROP COLUMN IF EXISTS genre_id;
DROP TABLE IF EXISTS genres;
