import Anthropic from '@anthropic-ai/sdk';
import { createClient } from '@supabase/supabase-js';
import { SYSTEM_PROMPT } from '../../../lib/prompt';

const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL,
  process.env.SUPABASE_SERVICE_KEY
);

// Charger l'état complet d'une partie
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

// Charger les messages pour le contexte conversationnel
async function loadConversationContext(partieId, currentCycle) {
  // 1. Tous les messages du cycle actuel
  const { data: currentCycleMessages } = await supabase
    .from('chat_messages')
    .select('role, content, cycle, created_at')
    .eq('partie_id', partieId)
    .eq('cycle', currentCycle)
    .order('created_at', { ascending: true });

  // 2. Les 5 derniers messages du cycle précédent
  const { data: previousCycleMessages } = await supabase
    .from('chat_messages')
    .select('role, content, cycle, created_at')
    .eq('partie_id', partieId)
    .eq('cycle', currentCycle - 1)
    .order('created_at', { ascending: false })
    .limit(5);

  // 3. Les résumés des 5 derniers cycles (hors cycle actuel et précédent)
  const { data: cycleResumes } = await supabase
    .from('cycle_resumes')
    .select('cycle, jour, date_jeu, resume, evenements_cles, relations_modifiees')
    .eq('partie_id', partieId)
    .lt('cycle', currentCycle - 1)
    .order('cycle', { ascending: false })
    .limit(5);

  return {
    currentCycleMessages: currentCycleMessages || [],
    previousCycleMessages: (previousCycleMessages || []).reverse(),
    cycleResumes: (cycleResumes || []).reverse()
  };
}

// Charger tous les messages chat (pour l'affichage)
async function loadChatMessages(partieId) {
  const { data } = await supabase
    .from('chat_messages')
    .select('role, content, created_at')
    .eq('partie_id', partieId)
    .order('created_at', { ascending: true });
  return data || [];
}

// Générer un résumé de cycle via Claude
async function generateCycleResume(partieId, cycle, messages, gameState) {
  if (!messages || messages.length === 0) return null;

  const prompt = `Résume ce cycle de jeu en 2-3 phrases maximum. Identifie aussi :
- Les événements clés (max 3)
- Les relations modifiées (nom du PNJ et changement)

Messages du cycle ${cycle} :
${messages.map(m => `${m.role}: ${m.content}`).join('\n\n')}

Réponds en JSON uniquement :
{
  "resume": "...",
  "evenements_cles": ["...", "..."],
  "relations_modifiees": [{"pnj": "...", "changement": "..."}]
}`;

  try {
    const response = await anthropic.messages.create({
      model: 'claude-sonnet-4-20250514',
      max_tokens: 500,
      messages: [{ role: 'user', content: prompt }]
    });

    let content = response.content[0].text.trim();
    if (content.startsWith('```json')) content = content.slice(7);
    if (content.startsWith('```')) content = content.slice(3);
    if (content.endsWith('```')) content = content.slice(0, -3);
    
    const parsed = JSON.parse(content.trim());

    // Sauvegarder le résumé
    await supabase.from('cycle_resumes').upsert({
      partie_id: partieId,
      cycle: cycle,
      jour: gameState?.partie?.jour,
      date_jeu: gameState?.partie?.date_jeu,
      resume: parsed.resume,
      evenements_cles: parsed.evenements_cles || [],
      relations_modifiees: parsed.relations_modifiees || []
    });

    return parsed;
  } catch (e) {
    console.error('Erreur génération résumé:', e);
    return null;
  }
}

// Construire le contexte conversationnel pour Claude
function buildConversationContext(conversationData, gameState, userMessage) {
  const { currentCycleMessages, previousCycleMessages, cycleResumes } = conversationData;
  
  let context = '';

  // Ajouter les résumés des cycles passés
  if (cycleResumes.length > 0) {
    context += '=== RÉSUMÉS DES CYCLES PRÉCÉDENTS ===\n';
    for (const r of cycleResumes) {
      context += `[Cycle ${r.cycle} - ${r.jour} ${r.date_jeu}] ${r.resume}\n`;
      if (r.evenements_cles?.length > 0) {
        context += `  → Événements: ${r.evenements_cles.join(', ')}\n`;
      }
    }
    context += '\n';
  }

  // Ajouter l'état actuel
  context += '=== ÉTAT ACTUEL ===\n';
  context += JSON.stringify(gameState, null, 2);
  context += '\n\n';

  // Ajouter les messages du cycle précédent (fin)
  if (previousCycleMessages.length > 0) {
    context += '=== FIN DU CYCLE PRÉCÉDENT ===\n';
    for (const m of previousCycleMessages) {
      context += `${m.role.toUpperCase()}: ${m.content}\n\n`;
    }
  }

  // Ajouter les messages du cycle actuel
  if (currentCycleMessages.length > 0) {
    context += '=== CYCLE ACTUEL ===\n';
    for (const m of currentCycleMessages) {
      context += `${m.role.toUpperCase()}: ${m.content}\n\n`;
    }
  }

  // Action du joueur
  context += '=== ACTION DU JOUEUR ===\n';
  context += userMessage;

  return context;
}

// Sauvegarder l'état
async function saveGameState(partieId, state) {
  const { partie, valentin, ia, contexte, pnj, arcs, historique, aVenir, lieux, horsChamp } = state;

  if (partie) {
    await supabase.from('parties').update({
      cycle_actuel: partie.cycle_actuel,
      jour: partie.jour,
      date_jeu: partie.date_jeu,
      heure: partie.heure
    }).eq('id', partieId);
  }

  if (valentin) {
    await supabase.from('valentin').upsert({ ...valentin, partie_id: partieId });
  }

  if (ia) {
    await supabase.from('ia_personnelle').upsert({ ...ia, partie_id: partieId });
  }

  if (contexte) {
    await supabase.from('contexte').upsert({ ...contexte, partie_id: partieId });
  }

  if (pnj && pnj.length > 0) {
    for (const p of pnj) {
      if (p.id) {
        await supabase.from('pnj').update(p).eq('id', p.id);
      } else {
        await supabase.from('pnj').insert({ ...p, partie_id: partieId });
      }
    }
  }

  if (arcs && arcs.length > 0) {
    for (const a of arcs) {
      if (a.id) {
        await supabase.from('arcs').update(a).eq('id', a.id);
      } else {
        await supabase.from('arcs').insert({ ...a, partie_id: partieId });
      }
    }
  }

  if (historique && historique.length > 0) {
    const latest = historique[0];
    if (latest && !latest.id) {
      await supabase.from('historique').insert({ ...latest, partie_id: partieId });
    }
  }

  if (aVenir && aVenir.length > 0) {
    for (const av of aVenir) {
      if (av.id) {
        await supabase.from('a_venir').update(av).eq('id', av.id);
      } else {
        await supabase.from('a_venir').insert({ ...av, partie_id: partieId });
      }
    }
  }

  if (lieux && lieux.length > 0) {
    for (const l of lieux) {
      if (!l.id) {
        await supabase.from('lieux').insert({ ...l, partie_id: partieId });
      }
    }
  }

  if (horsChamp && horsChamp.length > 0) {
    for (const hc of horsChamp) {
      if (!hc.id) {
        await supabase.from('hors_champ').insert({ ...hc, partie_id: partieId });
      }
    }
  }
}

// Supprimer une partie et toutes ses données
async function deleteGame(partieId) {
  await supabase.from('chat_messages').delete().eq('partie_id', partieId);
  await supabase.from('cycle_resumes').delete().eq('partie_id', partieId);
  await supabase.from('hors_champ').delete().eq('partie_id', partieId);
  await supabase.from('lieux').delete().eq('partie_id', partieId);
  await supabase.from('a_venir').delete().eq('partie_id', partieId);
  await supabase.from('historique').delete().eq('partie_id', partieId);
  await supabase.from('arcs').delete().eq('partie_id', partieId);
  await supabase.from('pnj').delete().eq('partie_id', partieId);
  await supabase.from('contexte').delete().eq('partie_id', partieId);
  await supabase.from('ia_personnelle').delete().eq('partie_id', partieId);
  await supabase.from('valentin').delete().eq('partie_id', partieId);
  await supabase.from('parties').delete().eq('id', partieId);
}

// Renommer une partie
async function renameGame(partieId, newName) {
  await supabase.from('parties').update({ nom: newName }).eq('id', partieId);
}

// Créer nouvelle partie
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
    const messages = await loadChatMessages(partieId);
    return Response.json({ state, messages });
  }

  if (action === 'list') {
    const { data } = await supabase.from('parties').select('id, nom, cycle_actuel, updated_at, created_at').eq('active', true).order('updated_at', { ascending: false });
    return Response.json({ parties: data });
  }

  if (action === 'new') {
    const partieId = await createNewGame();
    return Response.json({ partieId });
  }

  if (action === 'delete' && partieId) {
    await deleteGame(partieId);
    return Response.json({ success: true });
  }

  if (action === 'rename' && partieId) {
    const newName = searchParams.get('name');
    if (newName) {
      await renameGame(partieId, newName);
      return Response.json({ success: true });
    }
    return Response.json({ error: 'Nom manquant' }, { status: 400 });
  }

  return Response.json({ error: 'Action non reconnue' });
}

export async function POST(request) {
  try {
    const { message, partieId, gameState } = await request.json();

    const currentCycle = gameState?.partie?.cycle_actuel || gameState?.cycle || 1;
    const previousCycle = currentCycle - 1;

    // Charger le contexte conversationnel si partie existante
    let contextMessage;
    if (partieId && gameState && gameState.partie) {
      const conversationData = await loadConversationContext(partieId, currentCycle);
      contextMessage = buildConversationContext(conversationData, gameState, message);
    } else {
      contextMessage = 'Nouvelle partie. Lance le jeu. Génère tout au lancement.';
    }

    // Appel Claude
    const response = await anthropic.messages.create({
      model: 'claude-sonnet-4-20250514',
      max_tokens: 4096,
      system: SYSTEM_PROMPT,
      messages: [{ role: 'user', content: contextMessage }]
    });

    const content = response.content[0].text;

    let parsed;
    try {
      let cleanContent = content.trim();
      if (cleanContent.startsWith('```json')) cleanContent = cleanContent.slice(7);
      if (cleanContent.startsWith('```')) cleanContent = cleanContent.slice(3);
      if (cleanContent.endsWith('```')) cleanContent = cleanContent.slice(0, -3);
      parsed = JSON.parse(cleanContent.trim());
    } catch (e) {
      return Response.json({ content, raw: true });
    }

    // Détecter changement de cycle et générer résumé
    const newCycle = parsed.state?.cycle || currentCycle;
    if (partieId && newCycle > currentCycle) {
      // Charger les messages du cycle qui vient de se terminer
      const { data: cycleMessages } = await supabase
        .from('chat_messages')
        .select('role, content')
        .eq('partie_id', partieId)
        .eq('cycle', currentCycle)
        .order('created_at', { ascending: true });

      // Générer et sauvegarder le résumé
      await generateCycleResume(partieId, currentCycle, cycleMessages, gameState);
    }

    // Construire le texte narratif pour l'affichage
    let displayText = '';
    if (parsed.heure) displayText += `[${parsed.heure}] `;
    if (parsed.narratif) displayText += parsed.narratif;
    if (parsed.choix && parsed.choix.length > 0) {
      displayText += '\n\n' + parsed.choix.map((c, i) => `${i + 1}. ${c}`).join('\n');
    }

    // Sauvegarder l'état si partieId existe
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
    }

    // Sauvegarder messages chat avec le cycle
    if (partieId) {
      await supabase.from('chat_messages').insert([
        { partie_id: partieId, role: 'user', content: message, cycle: newCycle },
        { partie_id: partieId, role: 'assistant', content: displayText, cycle: newCycle }
      ]);
    }

    return Response.json({ 
      displayText,
      state: parsed.state,
      heure: parsed.heure
    });

  } catch (e) {
    console.error('Erreur:', e);
    return Response.json({ error: e.message }, { status: 500 });
  }
}
