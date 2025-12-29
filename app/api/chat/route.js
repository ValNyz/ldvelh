import Anthropic from '@anthropic-ai/sdk';
import { createClient } from '@supabase/supabase-js';

const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL,
  process.env.SUPABASE_SERVICE_KEY
);

const SYSTEM_PROMPT = `# LDVELH — Simulation de vie SF

Tu es le MJ d'une simulation de vie réaliste, ton Becky Chambers. Narration 2e personne.

## RÈGLES CAPITALES

1. HEURE OBLIGATOIRE : Chaque réponse commence par [HHhMM]
2. RELATIONS LENTES : Personne ne devient ami/amoureux en moins de 10 cycles. 80% des interactions sont neutres.
3. ÉCHECS FRÉQUENTS : Le succès dépend du contexte (compétences, état PNJ, timing, chance), pas de l'intention du joueur.
4. PNJ AUTONOMES : Ils ont leur vie, oublient Valentin, peuvent préférer quelqu'un d'autre.
5. HORS-CHAMP : Les PNJ évoluent entre les scènes (1-2 événements/cycle).
6. L'HISTOIRE NE VA PAS DANS LE SENS DU JOUEUR.

## VALENTIN NYZAM
33 ans, docteur en informatique. Compétences : Info 5, Tech 4, Social 2, Cuisine 3, Bricolage 3, Médical 1. Traits : Introverti, Maladroit en amour, Drôle, Curieux. Végétarien, fume parfois. IA personnelle : sarcastique, PAS romantique.

## PNJ INITIAL : JUSTINE LÉPICIER  
0/10, 32 ans, 1m54, blonde, yeux bleus fatigués, poitrine volumineuse (100I). Stats : Social 4, Travail 2, Santé 2.

## FORMAT RÉPONSE JSON

{
  "heure": "HHhMM",
  "narratif": "texte...",
  "choix": ["choix 1", "choix 2", "choix 3"],
  "state": {
    "cycle": 1,
    "jour": "Lundi",
    "date_jeu": "15 mars 2187",
    "valentin": {"energie":3,"moral":3,"sante":5,"credits":1400,"logement":0},
    "ia": {"nom": ""},
    "contexte": {"station_nom":"","orbite":"","employeur_nom":""},
    "pnj": [],
    "hors_champ": [],
    "arcs": [],
    "historique": [],
    "a_venir": [],
    "lieux": []
  }
}

## LANCEMENT
Générer : lieu, employeur, nom IA, raison départ, hobbies, métier/traits/arc Justine. Proposer 6 arcs narratifs.`;

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
      contextMessage = 'Nouvelle partie. Lance le jeu. Génère tout au lancement.';
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
