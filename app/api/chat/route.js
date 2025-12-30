import Anthropic from '@anthropic-ai/sdk';
import { createClient } from '@supabase/supabase-js';
import { SYSTEM_PROMPT } from '../../../lib/prompt';

// Configuration pour le streaming
export const dynamic = 'force-dynamic';

const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL,
  process.env.SUPABASE_SERVICE_KEY
);

// ============================================================================
// FONCTIONS DE RÉPARATION JSON
// ============================================================================

function tryFixJSON(jsonStr) {
  if (!jsonStr || typeof jsonStr !== 'string') return null;
  
  let fixed = jsonStr.trim();
  
  if (fixed.startsWith('```json')) fixed = fixed.slice(7);
  if (fixed.startsWith('```')) fixed = fixed.slice(3);
  if (fixed.endsWith('```')) fixed = fixed.slice(0, -3);
  fixed = fixed.trim();
  
  const firstBrace = fixed.indexOf('{');
  if (firstBrace > 0) {
    fixed = fixed.slice(firstBrace);
  } else if (firstBrace === -1) {
    return null;
  }
  
  try {
    return JSON.parse(fixed);
  } catch (e) {}
  
  let lastValidIndex = -1;
  let braceCount = 0;
  let inString = false;
  let escapeNext = false;
  
  for (let i = 0; i < fixed.length; i++) {
    const char = fixed[i];
    if (escapeNext) { escapeNext = false; continue; }
    if (char === '\\' && inString) { escapeNext = true; continue; }
    if (char === '"' && !escapeNext) { inString = !inString; continue; }
    if (!inString) {
      if (char === '{') braceCount++;
      if (char === '}') {
        braceCount--;
        if (braceCount === 0) lastValidIndex = i;
      }
    }
  }
  
  if (lastValidIndex > 0) {
    try { return JSON.parse(fixed.slice(0, lastValidIndex + 1)); } catch (e) {}
  }
  
  let openBraces = 0, openBrackets = 0;
  inString = false;
  escapeNext = false;
  
  for (let i = 0; i < fixed.length; i++) {
    const char = fixed[i];
    if (escapeNext) { escapeNext = false; continue; }
    if (char === '\\' && inString) { escapeNext = true; continue; }
    if (char === '"') { inString = !inString; continue; }
    if (!inString) {
      if (char === '{') openBraces++;
      if (char === '}') openBraces--;
      if (char === '[') openBrackets++;
      if (char === ']') openBrackets--;
    }
  }
  
  if (inString) fixed += '"';
  while (openBrackets > 0) { fixed += ']'; openBrackets--; }
  while (openBraces > 0) { fixed += '}'; openBraces--; }
  
  try { return JSON.parse(fixed); } catch (e) {}
  
  fixed = fixed.replace(/,(\s*[}\]])/g, '$1');
  fixed = fixed.replace(/:\s*([}\]])/g, ': null$1');
  fixed = fixed.replace(/:\s*,/g, ': null,');
  
  try { return JSON.parse(fixed); } catch (e) {
    console.error('JSON repair failed:', e.message);
    return null;
  }
}

function extractJSON(content) {
  if (!content) return null;
  
  if (content.trim().startsWith('{')) {
    const result = tryFixJSON(content);
    if (result) return result;
  }
  
  const lastBraceIndex = content.lastIndexOf('\n{');
  if (lastBraceIndex > 0) {
    const result = tryFixJSON(content.slice(lastBraceIndex + 1));
    if (result) return result;
  }
  
  const firstBraceIndex = content.indexOf('{');
  if (firstBraceIndex >= 0) {
    const result = tryFixJSON(content.slice(firstBraceIndex));
    if (result) return result;
  }
  
  return null;
}

// ============================================================================
// VALIDATION ET MERGE DU STATE
// ============================================================================

/**
 * Fusionne le nouveau state avec l'existant sans écraser avec undefined/null
 */
function mergeStateField(existing, updates) {
  if (updates === undefined || updates === null) return existing;
  if (typeof updates !== 'object' || Array.isArray(updates)) return updates;
  if (!existing || typeof existing !== 'object') return updates;
  
  const result = { ...existing };
  for (const key of Object.keys(updates)) {
    if (updates[key] !== undefined) {
      result[key] = updates[key];
    }
  }
  return result;
}

/**
 * Valide et fusionne le state complet de Claude avec l'état existant
 */
function validateAndMergeState(existingState, newState) {
  if (!newState) return null;
  
  return {
    cycle: newState.cycle ?? existingState?.partie?.cycle_actuel ?? 1,
    jour: newState.jour ?? existingState?.partie?.jour ?? 'Lundi',
    date_jeu: newState.date_jeu ?? existingState?.partie?.date_jeu,
    valentin: mergeStateField(existingState?.valentin, newState.valentin),
    ia: mergeStateField(existingState?.ia, newState.ia),
    contexte: mergeStateField(existingState?.contexte, newState.contexte),
    pnj: Array.isArray(newState.pnj) ? newState.pnj : (existingState?.pnj || []),
    arcs: Array.isArray(newState.arcs) ? newState.arcs : (existingState?.arcs || []),
    historique: Array.isArray(newState.historique) ? newState.historique : (existingState?.historique || []),
    a_venir: Array.isArray(newState.a_venir) ? newState.a_venir : (existingState?.aVenir || []),
    lieux: Array.isArray(newState.lieux) ? newState.lieux : (existingState?.lieux || []),
    hors_champ: Array.isArray(newState.hors_champ) ? newState.hors_champ : (existingState?.horsChamp || [])
  };
}

// ============================================================================
// FONCTIONS DE CHARGEMENT DES DONNÉES
// ============================================================================

async function loadGameState(partieId) {
  const [partie, valentin, ia, contexte, pnj, arcs, historique, aVenir, lieux, horsChamp] = await Promise.all([
    supabase.from('parties').select('*').eq('id', partieId).single(),
    supabase.from('valentin').select('*').eq('partie_id', partieId).single(),
    supabase.from('ia_personnelle').select('*').eq('partie_id', partieId).single(),
    supabase.from('contexte').select('*').eq('partie_id', partieId).single(),
    supabase.from('pnj').select('*').eq('partie_id', partieId),
    supabase.from('arcs').select('*').eq('partie_id', partieId),
    supabase.from('historique').select('*').eq('partie_id', partieId).order('cycle', { ascending: false }).limit(3),
    supabase.from('a_venir').select('*').eq('partie_id', partieId).eq('realise', false),
    supabase.from('lieux').select('*').eq('partie_id', partieId),
    supabase.from('hors_champ').select('*').eq('partie_id', partieId).order('cycle', { ascending: false }).limit(3)
  ]);

  return {
    partie: partie.data, valentin: valentin.data, ia: ia.data, contexte: contexte.data,
    pnj: pnj.data || [], arcs: arcs.data || [], historique: historique.data || [],
    aVenir: aVenir.data || [], lieux: lieux.data || [], horsChamp: horsChamp.data || []
  };
}

async function loadConversationContext(partieId, currentCycle) {
  const [currentCycleRes, previousCycleRes, cycleResumesRes] = await Promise.all([
    supabase.from('chat_messages').select('role, content, cycle, created_at')
      .eq('partie_id', partieId).eq('cycle', currentCycle).order('created_at', { ascending: true }),
    supabase.from('chat_messages').select('role, content, cycle, created_at')
      .eq('partie_id', partieId).eq('cycle', currentCycle - 1).order('created_at', { ascending: false }).limit(3),
    supabase.from('cycle_resumes').select('cycle, jour, date_jeu, resume, evenements_cles')
      .eq('partie_id', partieId).lt('cycle', currentCycle - 1).order('cycle', { ascending: false }).limit(3)
  ]);

  return {
    currentCycleMessages: currentCycleRes.data || [],
    previousCycleMessages: (previousCycleRes.data || []).reverse(),
    cycleResumes: (cycleResumesRes.data || []).reverse()
  };
}

async function loadChatMessages(partieId) {
  const { data, error } = await supabase.from('chat_messages').select('role, content, cycle, created_at')
    .eq('partie_id', partieId).order('created_at', { ascending: true });
  if (error) { console.error('Erreur chargement messages:', error); return []; }
  console.log(`Loaded ${data?.length || 0} messages for partie ${partieId}`);
  return data || [];
}

// ============================================================================
// GÉNÉRATION DE RÉSUMÉ DE CYCLE
// ============================================================================

async function generateCycleResume(partieId, cycle, messages, gameState) {
  if (!messages || messages.length === 0) return null;

  const prompt = `Résume ce cycle en 2 phrases max. Liste max 2 événements clés.

Cycle ${cycle}:
${messages.map(m => `${m.role}: ${m.content.slice(0, 200)}`).join(' | ')}

Réponds en JSON uniquement:
{"resume": "...", "evenements_cles": ["...", "..."]}`;

  try {
    const response = await anthropic.messages.create({
      model: 'claude-sonnet-4-20250514',
      max_tokens: 300,
      messages: [{ role: 'user', content: prompt }]
    });

    let content = response.content[0].text.trim();
    if (content.startsWith('```json')) content = content.slice(7);
    if (content.startsWith('```')) content = content.slice(3);
    if (content.endsWith('```')) content = content.slice(0, -3);
    
    const parsed = JSON.parse(content.trim());

    await supabase.from('cycle_resumes').upsert({
      partie_id: partieId, cycle: cycle, jour: gameState?.partie?.jour,
      date_jeu: gameState?.partie?.date_jeu, resume: parsed.resume,
      evenements_cles: parsed.evenements_cles || []
    });

    return parsed;
  } catch (e) {
    console.error('Erreur génération résumé:', e);
    return null;
  }
}

// ============================================================================
// CONSTRUCTION DU CONTEXTE POUR CLAUDE
// ============================================================================

function buildConversationContext(conversationData, gameState, userMessage) {
  const { currentCycleMessages, previousCycleMessages, cycleResumes } = conversationData;
  let context = '';

  if (cycleResumes.length > 0) {
    context += '=== RÉSUMÉS CYCLES PRÉCÉDENTS ===\n';
    for (const r of cycleResumes) context += `[Cycle ${r.cycle}] ${r.resume}\n`;
    context += '\n';
  }

  context += '=== ÉTAT ACTUEL ===\n';
  context += JSON.stringify(gameState, null, 1);
  context += '\n\n';

  if (previousCycleMessages.length > 0) {
    context += '=== FIN CYCLE PRÉCÉDENT ===\n';
    for (const m of previousCycleMessages.slice(-2)) {
      context += `${m.role.toUpperCase()}: ${m.content.slice(0, 300)}\n`;
    }
    context += '\n';
  }

  if (currentCycleMessages.length > 0) {
    context += '=== CYCLE ACTUEL ===\n';
    for (const m of currentCycleMessages.slice(-4)) {
      context += `${m.role.toUpperCase()}: ${m.content}\n\n`;
    }
  }

  context += '=== ACTION DU JOUEUR ===\n';
  context += userMessage;

  return context;
}

// ============================================================================
// SAUVEGARDE DE L'ÉTAT
// ============================================================================

async function saveGameState(partieId, state) {
  const { partie, valentin, ia, contexte, pnj, arcs, historique, aVenir, lieux, horsChamp } = state;

  const batch1 = [];
  if (partie) {
    batch1.push(supabase.from('parties').update({
      cycle_actuel: partie.cycle_actuel, jour: partie.jour, date_jeu: partie.date_jeu, heure: partie.heure
    }).eq('id', partieId));
  }
  if (valentin) batch1.push(supabase.from('valentin').upsert({ ...valentin, partie_id: partieId }));
  if (ia) batch1.push(supabase.from('ia_personnelle').upsert({ ...ia, partie_id: partieId }));
  if (contexte) batch1.push(supabase.from('contexte').upsert({ ...contexte, partie_id: partieId }));
  await Promise.all(batch1);

  const batch2 = [];

  if (pnj && pnj.length > 0) {
    const pnjToUpdate = pnj.filter(p => p.id);
    const pnjToInsert = pnj.filter(p => !p.id).map(p => ({ ...p, partie_id: partieId }));
    for (const p of pnjToUpdate) batch2.push(supabase.from('pnj').update(p).eq('id', p.id));
    if (pnjToInsert.length > 0) batch2.push(supabase.from('pnj').insert(pnjToInsert));
  }

  if (arcs && arcs.length > 0) {
    const arcsToUpdate = arcs.filter(a => a.id);
    const arcsToInsert = arcs.filter(a => !a.id).map(a => ({ ...a, partie_id: partieId }));
    for (const a of arcsToUpdate) batch2.push(supabase.from('arcs').update(a).eq('id', a.id));
    if (arcsToInsert.length > 0) batch2.push(supabase.from('arcs').insert(arcsToInsert));
  }

  if (historique && historique.length > 0) {
    const newHistorique = historique.filter(h => !h.id).map(h => ({ ...h, partie_id: partieId }));
    if (newHistorique.length > 0) batch2.push(supabase.from('historique').insert(newHistorique));
  }

  if (aVenir && aVenir.length > 0) {
    const aVenirToUpdate = aVenir.filter(av => av.id);
    const aVenirToInsert = aVenir.filter(av => !av.id).map(av => ({ ...av, partie_id: partieId }));
    for (const av of aVenirToUpdate) batch2.push(supabase.from('a_venir').update(av).eq('id', av.id));
    if (aVenirToInsert.length > 0) batch2.push(supabase.from('a_venir').insert(aVenirToInsert));
  }

  if (lieux && lieux.length > 0) {
    const newLieux = lieux.filter(l => !l.id).map(l => ({ ...l, partie_id: partieId }));
    if (newLieux.length > 0) batch2.push(supabase.from('lieux').insert(newLieux));
  }

  if (horsChamp && horsChamp.length > 0) {
    const newHorsChamp = horsChamp.filter(hc => !hc.id).map(hc => ({ ...hc, partie_id: partieId }));
    if (newHorsChamp.length > 0) batch2.push(supabase.from('hors_champ').insert(newHorsChamp));
  }

  if (batch2.length > 0) await Promise.all(batch2);
}

// ============================================================================
// GESTION DES PARTIES
// ============================================================================

async function deleteGame(partieId) {
  await Promise.all([
    supabase.from('chat_messages').delete().eq('partie_id', partieId),
    supabase.from('cycle_resumes').delete().eq('partie_id', partieId),
    supabase.from('hors_champ').delete().eq('partie_id', partieId),
    supabase.from('lieux').delete().eq('partie_id', partieId),
    supabase.from('a_venir').delete().eq('partie_id', partieId),
    supabase.from('historique').delete().eq('partie_id', partieId),
    supabase.from('arcs').delete().eq('partie_id', partieId),
    supabase.from('pnj').delete().eq('partie_id', partieId),
    supabase.from('contexte').delete().eq('partie_id', partieId),
    supabase.from('ia_personnelle').delete().eq('partie_id', partieId),
    supabase.from('valentin').delete().eq('partie_id', partieId)
  ]);
  await supabase.from('parties').delete().eq('id', partieId);
}

async function renameGame(partieId, newName) {
  await supabase.from('parties').update({ nom: newName }).eq('id', partieId);
}

async function createNewGame() {
  try {
    const { data: partie, error: partieError } = await supabase
      .from('parties').insert({ nom: 'Nouvelle partie', cycle_actuel: 1, active: true }).select().single();
    if (partieError) { console.error('Erreur création partie:', partieError); throw partieError; }

    const [valentinRes, iaRes, contexteRes] = await Promise.all([
      supabase.from('valentin').insert({ partie_id: partie.id }),
      supabase.from('ia_personnelle').insert({ partie_id: partie.id }),
      supabase.from('contexte').insert({ partie_id: partie.id })
    ]);

    if (valentinRes.error) console.error('Erreur valentin:', valentinRes.error);
    if (iaRes.error) console.error('Erreur ia:', iaRes.error);
    if (contexteRes.error) console.error('Erreur contexte:', contexteRes.error);

    return partie.id;
  } catch (e) {
    console.error('Erreur createNewGame:', e);
    throw e;
  }
}

// ============================================================================
// HANDLERS HTTP
// ============================================================================

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
    const { data } = await supabase.from('parties')
      .select('id, nom, cycle_actuel, updated_at, created_at')
      .eq('active', true).order('updated_at', { ascending: false });
    return Response.json({ parties: data });
  }

  if (action === 'new') {
    try {
      const partieId = await createNewGame();
      return Response.json({ partieId });
    } catch (e) {
      return Response.json({ error: e.message }, { status: 500 });
    }
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

export async function DELETE(request) {
  try {
    const { partieId, fromIndex } = await request.json();
    if (!partieId) return Response.json({ error: 'partieId manquant' }, { status: 400 });

    const { data: allMessages } = await supabase.from('chat_messages')
      .select('id, created_at').eq('partie_id', partieId).order('created_at', { ascending: true });

    if (!allMessages || fromIndex >= allMessages.length) return Response.json({ success: true });

    const messagesToDelete = allMessages.slice(fromIndex).map(m => m.id);
    if (messagesToDelete.length > 0) {
      await supabase.from('chat_messages').delete().in('id', messagesToDelete);
    }

    return Response.json({ success: true, deleted: messagesToDelete.length });
  } catch (e) {
    console.error('Erreur DELETE:', e);
    return Response.json({ error: e.message }, { status: 500 });
  }
}

export async function POST(request) {
  try {
    const { message, partieId, gameState } = await request.json();
    const currentCycle = gameState?.partie?.cycle_actuel || gameState?.cycle || 1;

    let contextMessage;
    if (partieId && gameState && gameState.partie) {
      const conversationData = await loadConversationContext(partieId, currentCycle);
      contextMessage = buildConversationContext(conversationData, gameState, message);
    } else {
      contextMessage = 'Nouvelle partie. Lance le jeu. Génère tout au lancement.';
    }

    const { readable, writable } = new TransformStream();
    const writer = writable.getWriter();
    const encoder = new TextEncoder();

    (async () => {
      let fullContent = '';
      let parsed = null;
      let displayText = '';
      let cycleForSave = currentCycle;

      try {
        const streamResponse = await anthropic.messages.stream({
          model: 'claude-sonnet-4-20250514',
          max_tokens: 8192,
          system: SYSTEM_PROMPT,
          messages: [{ role: 'user', content: contextMessage }]
        });

        for await (const event of streamResponse) {
          if (event.type === 'content_block_delta' && event.delta?.text) {
            const chunk = event.delta.text;
            fullContent += chunk;
            await writer.write(encoder.encode(`data: ${JSON.stringify({ type: 'chunk', content: chunk })}\n\n`));
          }
        }

        console.log('>>> 1. Stream terminé');

        const finalMessage = await streamResponse.finalMessage();
        if (finalMessage.stop_reason === 'max_tokens') {
          console.warn('⚠️ Réponse tronquée! max_tokens atteint. Usage:', finalMessage.usage);
        } else {
          console.log('✓ Réponse complète. Usage:', finalMessage.usage);
        }

        const rawParsed = extractJSON(fullContent);
        console.log('>>> 2. JSON parsé, rawParsed est null?', rawParsed === null);

        // Valider et fusionner le state avec l'existant
        const validatedState = rawParsed?.state ? validateAndMergeState(gameState, rawParsed.state) : null;
        parsed = rawParsed ? { ...rawParsed, state: validatedState } : null;

        if (parsed) {
          displayText = '';
          if (parsed.heure) displayText += `[${parsed.heure}] `;
          if (parsed.narratif) displayText += parsed.narratif;
          if (parsed.choix && parsed.choix.length > 0) {
            displayText += '\n\n' + parsed.choix.map((c, i) => `${i + 1}. ${c}`).join('\n');
          }
          cycleForSave = validatedState?.cycle || currentCycle;
        } else {
          console.error('JSON non parsable, utilisation du texte brut');
          displayText = fullContent.replace(/```json[\s\S]*?```/g, '').replace(/\{[\s\S]*\}$/g, '').trim();
          if (!displayText) displayText = "Une erreur s'est produite lors de la génération. Réessaie.";
        }

        // Envoyer le message final avec les données parsées
        await writer.write(encoder.encode(`data: ${JSON.stringify({ 
          type: 'done', 
          displayText,
          state: parsed?.state,
          heure: parsed?.heure
        })}\n\n`));

        // CORRECTION: Sauvegarder les messages AVANT de signaler "saved"
        if (partieId) {
          try {
            const saveStart = Date.now();
            await Promise.all([
              supabase.from('chat_messages').insert({
                partie_id: partieId, role: 'user', content: message, cycle: cycleForSave
              }),
              supabase.from('chat_messages').insert({
                partie_id: partieId, role: 'assistant', content: displayText, cycle: cycleForSave
              })
            ]);
            console.log(`>>> 3. Messages saved in ${Date.now() - saveStart}ms`);
          } catch (err) {
            console.error('Erreur sauvegarde messages:', err);
          }
        }

        // Signaler que la sauvegarde est terminée
        await writer.write(encoder.encode(`data: ${JSON.stringify({ type: 'saved' })}\n\n`));

      } catch (error) {
        console.error('Streaming error:', error);
        try {
          await writer.write(encoder.encode(`data: ${JSON.stringify({ type: 'error', error: error.message })}\n\n`));
        } catch (e) {}
      } finally {
        try { await writer.close(); } catch (e) {}
      }
      
      // === TÂCHES EN ARRIÈRE-PLAN (après fermeture du stream) ===
      
      // Sauvegarder l'état du jeu (non-bloquant, peut rester async)
      if (partieId && parsed?.state) {
        saveGameState(partieId, {
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
        }).catch(err => console.error('Erreur sauvegarde state:', err));
      }

      // Générer résumé si changement de cycle (non-bloquant)
      if (partieId && parsed && cycleForSave > currentCycle) {
        supabase.from('chat_messages').select('role, content')
          .eq('partie_id', partieId).eq('cycle', currentCycle).order('created_at', { ascending: true })
          .then(({ data: cycleMessages }) => {
            if (cycleMessages) {
              generateCycleResume(partieId, currentCycle, cycleMessages, gameState)
                .catch(err => console.error('Erreur génération résumé:', err));
            }
          })
          .catch(err => console.error('Erreur chargement messages cycle:', err));
      }
    })();

    return new Response(readable, {
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache, no-transform',
        'Connection': 'keep-alive',
        'X-Accel-Buffering': 'no',
      },
    });

  } catch (e) {
    console.error('Erreur POST:', e);
    return Response.json({ error: e.message }, { status: 500 });
  }
}
