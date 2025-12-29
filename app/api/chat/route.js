import Anthropic from '@anthropic-ai/sdk';
import { createClient } from '@supabase/supabase-js';

const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL,
  process.env.SUPABASE_SERVICE_KEY
);

const SYSTEM_PROMPT = `# LDVELH — Chroniques de l'Exil Stellaire

Tu es le MJ d'une simulation de vie SF réaliste. Ton Becky Chambers (Les Voyageurs).

## TON & ATMOSPHÈRE

Style Becky Chambers :
- Le quotidien compte. Descriptions sensorielles (odeurs recyclées, bourdonnement des systèmes, goût du café de station).
- Conversations qui divaguent naturellement, temps morts assumés, rituels domestiques.
- Mélancolie douce, chaleur dans les petits détails. Un bon repas partagé peut être le moment fort d'une journée.
- Les enjeux sont à échelle humaine : garder un ami, trouver sa place, payer son loyer, réparer une relation.
- La diversité (espèces, cultures, corps, orientations) est banale, pas exotique. Personne ne s'en étonne.
- Technologie usée, rafistolée, fonctionnelle. Rien n'est neuf ni rutilant.
- L'espace est hostile mais quotidien — comme la mer pour un marin.

## UNIVERS

Système solaire, 22e siècle. L'humanité s'est étendue : stations orbitales, bases lunaires, colonies martiennes, habitats sur astéroïdes, avant-postes autour de Jupiter et Saturne.

Lieux possibles pour la génération :
- Station orbitale terrestre (populaire, diverse, bruyante)
- Base lunaire (administrative, froide, efficace)
- Station martienne (pionnière, rude, communautaire)
- Habitat sur astéroïde de la Ceinture (minier, isolé, solidaire)
- Station jovienne (scientifique, lointaine, étrange lumière)
- Complexe autour de Saturne (frontière, mystérieux, contemplatif)

Chaque lieu a : des secteurs (résidentiel, commercial, industriel, agricole), des bars, des marchés, une ambiance propre.

Espèces : Humains uniquement, mais diversité culturelle énorme (Terriens, Lunaires, Martiens, Ceinturiens — accents, coutumes, tensions légères).

## RÈGLES CAPITALES

1. HEURE OBLIGATOIRE : Chaque réponse commence par [HHhMM]

2. RELATIONS LENTES : 
   - Personne ne devient ami/amoureux en moins de 10 cycles
   - 80% des interactions sont neutres, fonctionnelles, oubliables
   - Être gentil est NORMAL, pas un exploit qui mérite récompense
   - Les gens oublient Valentin, ont leur vie, leurs soucis

3. ÉCHECS FRÉQUENTS :
   - Le succès dépend du contexte, pas de l'intention du joueur
   - Social 2/5 = Valentin se plante souvent en interaction
   - Une bonne idée au mauvais moment reste un échec

4. PNJ AUTONOMES :
   - Ils ont leur vie qui continue sans Valentin
   - Ils peuvent préférer quelqu'un d'autre
   - Certains ne colleront JAMAIS avec lui

5. HORS-CHAMP OBLIGATOIRE :
   - 1-2 événements par cycle pour les PNJ actifs
   - Leurs arcs avancent sans Valentin
   - Certains événements restent invisibles jusqu'à découverte

6. L'HISTOIRE NE VA PAS DANS LE SENS DU JOUEUR :
   - Opportunités manquées qui ne reviennent pas
   - Résolutions décevantes possibles
   - Le monde est indifférent aux désirs de Valentin

## VALENTIN NYZAM

33 ans, docteur en informatique, vient d'arriver pour un nouveau poste.
1m78, brun dégarni, barbe, implants rétiniens.

Compétences : Informatique 5, Systèmes 4, Social 2, Cuisine 3, Bricolage 3, Médical 1

Traits : Introverti (extraverti avec alcool), Maladroit en amour, Drôle par défense, Curieux, Romantique malgré lui

Végétarien, fume occasionnellement. A codé sa propre IA personnelle (voix sensuelle, sarcastique, PAS un intérêt romantique).

## PNJ INITIAL : JUSTINE LÉPICIER

- 32 ans, humaine
- 1m54, 72kg, courbes prononcées, poitrine volumineuse (100I), blonde en désordre, yeux bleus fatigués, cernes permanents
- Stats : Social 4/5, Travail 2/5, Santé 2/5
- Relation initiale : 0/10 (inconnue)

À générer au lancement : son métier, ses traits de personnalité, son arc narratif, son domicile.

Progression romantique LENTE : Inconnus → Indifférence → Reconnaissance → Sympathie → Curiosité → Intérêt → Attirance (4-5 interactions positives espacées par étape).

## GÉNÉRATION INITIALE

Au lancement, générer :
1. Le lieu (station/base/habitat dans le système solaire) avec nom, orbite, population, ambiance
2. L'employeur de Valentin (institut de recherche, entreprise tech, administration)
3. Le nom et la personnalité de son IA
4. Sa raison de départ (pourquoi a-t-il quitté son ancien poste ?)
5. 1-2 hobbies en plus de la cuisine
6. Le métier, les traits (2-3) et l'arc de Justine
7. 2-3 lieux importants (bar habituel, marché, lieu de travail)
8. Proposer 6 arcs narratifs au joueur (2 pro, 2 perso, 2 station)

## FORMAT RÉPONSE JSON

{
  "heure": "HHhMM",
  "narratif": "texte de la scène avec descriptions sensorielles, ton Chambers...",
  "choix": ["choix 1", "choix 2", "choix 3"],
  "state": {
    "cycle": 1,
    "jour": "Lundi",
    "date_jeu": "15 mars 2247",
    "valentin": {
      "energie": 3,
      "moral": 3,
      "sante": 5,
      "credits": 1400,
      "logement": 0,
      "competences": {"informatique":5,"systemes":4,"social":2,"cuisine":3,"bricolage":3,"medical":1},
      "traits": ["Introverti","Maladroit en amour","Drôle par défense","Curieux","Romantique malgré lui"],
      "hobbies": ["Cuisine"],
      "inventaire": [],
      "raison_depart": "",
      "poste": ""
    },
    "ia": {"nom": "", "traits": ["Sarcastique","Pragmatique"]},
    "contexte": {
      "station_nom": "",
      "station_type": "",
      "orbite": "",
      "population": 0,
      "employeur_nom": "",
      "employeur_type": "",
      "ambiance": ""
    },
    "pnj": [{
      "nom": "Justine Lépicier",
      "relation": 0,
      "disposition": "neutre",
      "traits": [],
      "arc": "",
      "metier": "",
      "stat_social": 4,
      "stat_travail": 2,
      "stat_sante": 2,
      "domicile": "",
      "etape_romantique": 0
    }],
    "hors_champ": [],
    "arcs": [],
    "historique": [],
    "a_venir": [],
    "lieux": []
  }
}`;

async function loadGameState(partieId) {
  const [partie, valentin, ia, contexte, pnj, arcs, historique, aVenir, lieux, horsChamp] = await Promise.all([
    supabase.from('parties').select('*').eq('id', partieId).single(),
    supabase.from('valentin').select('*').eq('partie_id', partieId).single(),
    supabase.from('ia_personnelle').select('*').eq('partie_id', partieId).single(),
    supabase.from('contexte').select('*').eq('partie_id', partieId).single(),
    supabase.from('pnj').select('*').eq('partie_id', partieId),
    supabase.from('arcs').select('*').eq('partie_id', partieId),
    supabase.from('historique').select('*').eq('partie_id', partieId).order('cycle', { ascending: false }).limit(10),
    supabase.from('a_venir').select('*').eq('partie_id', partieId).eq('realise', false),
    supabase.from('lieux').select('*').eq('partie_id', partieId),
    supabase.from('hors_champ').select('*').eq('partie_id', partieId).order('cycle', { ascending: false }).limit(20)
  ]);
  return {
    partie: partie.data,
    valentin: valentin.data,
    ia: ia.data,
    contexte: contexte.data,
    pnj: pnj.data || [],
    arcs: arcs.data || [],
    historique: historique.data || [],
    aVenir: aVenir.data || [],
    lieux: lieux.data || [],
    horsChamp: horsChamp.data || []
  };
}

async function saveGameState(partieId, state) {
  if (state.partie) {
    await supabase.from('parties').update({
      cycle_actuel: state.partie.cycle_actuel,
      jour: state.partie.jour,
      date_jeu: state.partie.date_jeu,
      heure: state.partie.heure
    }).eq('id', partieId);
  }
  if (state.valentin) {
    await supabase.from('valentin').upsert({ ...state.valentin, partie_id: partieId });
  }
  if (state.ia) {
    await supabase.from('ia_personnelle').upsert({ ...state.ia, partie_id: partieId });
  }
  if (state.contexte) {
    await supabase.from('contexte').upsert({ ...state.contexte, partie_id: partieId });
  }
  if (state.pnj?.length > 0) {
    for (const p of state.pnj) {
      if (p.id) {
        await supabase.from('pnj').update(p).eq('id', p.id);
      } else {
        await supabase.from('pnj').insert({ ...p, partie_id: partieId });
      }
    }
  }
  if (state.arcs?.length > 0) {
    for (const a of state.arcs) {
      if (a.id) {
        await supabase.from('arcs').update(a).eq('id', a.id);
      } else {
        await supabase.from('arcs').insert({ ...a, partie_id: partieId });
      }
    }
  }
  if (state.historique?.length > 0) {
    const latest = state.historique[0];
    if (latest && !latest.id) {
      await supabase.from('historique').insert({ ...latest, partie_id: partieId });
    }
  }
  if (state.aVenir?.length > 0) {
    for (const av of state.aVenir) {
      if (av.id) {
        await supabase.from('a_venir').update(av).eq('id', av.id);
      } else {
        await supabase.from('a_venir').insert({ ...av, partie_id: partieId });
      }
    }
  }
  if (state.lieux?.length > 0) {
    for (const l of state.lieux) {
      if (!l.id) {
        await supabase.from('lieux').insert({ ...l, partie_id: partieId });
      }
    }
  }
  if (state.horsChamp?.length > 0) {
    for (const hc of state.horsChamp) {
      if (!hc.id) {
        await supabase.from('hors_champ').insert({ ...hc, partie_id: partieId });
      }
    }
  }
}

async function createNewGame() {
  const { data: partie } = await supabase.from('parties').insert({ nom: 'Nouvelle partie' }).select().single();
  await supabase.from('valentin').insert({ partie_id: partie.id });
  await supabase.from('ia_personnelle').insert({ partie_id: partie.id });
  await supabase.from('contexte').insert({ partie_id: partie.id });
  return partie.id;
}

export async function GET(request) {
  const { searchParams } = new URL(request.url);
  const action = searchParams.get('action');
  const partieId = searchParams.get('partieId');

  if (action === 'load' && partieId) {
    const state = await loadGameState(partieId);
    return Response.json({ state });
  }
  if (action === 'list') {
    const { data } = await supabase.from('parties').select('id, nom, cycle_actuel, updated_at').eq('active', true).order('updated_at', { ascending: false });
    return Response.json({ parties: data });
  }
  if (action === 'new') {
    const partieId = await createNewGame();
    return Response.json({ partieId });
  }
  return Response.json({ error: 'Action non reconnue' });
}

export async function POST(request) {
  try {
    const { message, partieId, gameState } = await request.json();

    let contextMessage;
    if (gameState && gameState.partie) {
      contextMessage = `État actuel:\n${JSON.stringify(gameState, null, 2)}\n\nAction du joueur: ${message}`;
    } else {
      contextMessage = 'Nouvelle partie. Lance le jeu selon les instructions. Génère tout (lieu, IA, contexte, Justine, lieux) puis propose les 6 arcs narratifs au joueur.';
    }

    const response = await anthropic.messages.create({
      model: 'claude-sonnet-4-20250514',
      max_tokens: 4096,
      system: SYSTEM_PROMPT,
      messages: [{ role: 'user', content: contextMessage }]
    });

    const content = response.content[0].text;

    let parsed;
    try {
      parsed = JSON.parse(content);
    } catch (e) {
      return Response.json({ content, raw: true });
    }

    if (partieId && parsed.state) {
      await saveGameState(partieId, {
        partie: { cycle_actuel: parsed.state.cycle, jour: parsed.state.jour, date_jeu: parsed.state.date_jeu, heure: parsed.heure },
        valentin: parsed.state.valentin,
        ia: parsed.state.ia,
        contexte: parsed.state.contexte,
        pnj: parsed.state.pnj,
        arcs: parsed.state.arcs,
        historique: parsed.state.historique,
        aVenir: parsed.state.a_venir,
        lieux: parsed.state.lieux,
        horsChamp: parsed.state.hors_champ
      });

      await supabase.from('chat_messages').insert([
        { partie_id: partieId, role: 'user', content: message, cycle: parsed.state?.cycle },
        { partie_id: partieId, role: 'assistant', content: parsed.narratif, cycle: parsed.state?.cycle }
      ]);
    }

    return Response.json({ parsed });

  } catch (e) {
    console.error('Erreur:', e);
    return Response.json({ error: e.message }, { status: 500 });
  }
}
