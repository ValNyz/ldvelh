import Anthropic from '@anthropic-ai/sdk';
import { createClient } from '@supabase/supabase-js';
import { SYSTEM_PROMPT } from '../../../lib/prompt';

export const dynamic = 'force-dynamic';

// Fonction améliorée pour réparer un JSON mal formé
function tryFixJSON(jsonStr) {
  if (!jsonStr || typeof jsonStr !== 'string') return null;
  
  let fixed = jsonStr.trim();
  
  // Enlever les backticks markdown
  if (fixed.startsWith('```json')) fixed = fixed.slice(7);
  if (fixed.startsWith('```')) fixed = fixed.slice(3);
  if (fixed.endsWith('```')) fixed = fixed.slice(0, -3);
  fixed = fixed.trim();
  
  // Si ça ne commence pas par {, chercher le premier {
  const firstBrace = fixed.indexOf('{');
  if (firstBrace > 0) {
    fixed = fixed.slice(firstBrace);
  } else if (firstBrace === -1) {
    return null;
  }
  
  // Essayer de parser directement
  try {
    return JSON.parse(fixed);
  } catch (e) {}
  
  // Trouver le dernier } qui ferme correctement le JSON
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
    try {
      return JSON.parse(fixed.slice(0, lastValidIndex + 1));
    } catch (e) {}
  }
  
  // Compter et fermer les accolades/crochets manquants
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
  
  try {
    return JSON.parse(fixed);
  } catch (e) {}
  
  // Corrections supplémentaires
  fixed = fixed.replace(/,(\s*[}\]])/g, '$1');
  fixed = fixed.replace(/:\s*([}\]])/g, ': null$1');
  fixed = fixed.replace(/:\s*,/g, ': null,');
  
  try {
    return JSON.parse(fixed);
  } catch (e) {
    console.error('JSON repair failed:', e.message);
    return null;
  }
}

// Extraire le JSON de la réponse
function extractJSON(content) {
  if (!content) return null;
  
  // Méthode 1: JSON pur
  if (content.trim().startsWith('{')) {
    const result = tryFixJSON(content);
    if (result) return result;
  }
  
  // Méthode 2: JSON après du texte
  const lastBraceIndex = content.lastIndexOf('\n{');
  if (lastBraceIndex > 0) {
    const result = tryFixJSON(content.slice(lastBraceIndex + 1));
    if (result) return result;
  }
  
  // Méthode 3: Premier { trouvé
  const firstBraceIndex = content.indexOf('{');
  if (firstBraceIndex >= 0) {
    const result = tryFixJSON(content.slice(firstBraceIndex));
    if (result) return result;
  }
  
  return null;
}

const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
const supabase = createClient(process.env.NEXT_PUBLIC_SUPABASE_URL, process.env.SUPABASE_SERVICE_KEY);

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
    supabase.from('chat_messages').select('role, content, cycle, created_at').eq('partie_id', partieId).eq('cycle', currentCycle).order('created_at', { ascending: true }),
    supabase.from('chat_messages').select('role, content, cycle, created_at').eq('partie_id', partieId).eq('cycle', currentCycle - 1).order('created_at', { ascending: false }).limit(3),
    supabase.from('cycle_resumes').select('cycle, jour, date_jeu, resume, evenements_cles').eq('partie_id', partieId).lt('cycle', currentCycle - 1).order('cycle', { ascending: false }).limit(3)
  ]);

  return {
    currentCycleMessages: currentCycleRes.data || [],
    previousCycleMessages: (previousCycleRes.data || []).reverse(),
    cycleResumes: (cycleResumesRes.data || []).reverse()
  };
}

async function loadChatMessages(partieId) {
  const { data } = await supabase.from('chat_messages').select('role, content, cycle, created_at').eq('partie_id', partieId).order('created_at', { ascending: true });
  return data || [];
}

async function generateCycleResume(partieId, cycle, messages, gameState) {
  if (!messages || messages.length === 0) return null;

  const prompt = `Résume ce cycle en 2 phrases. Liste max 2 événements clés.
Cycle ${cycle}: ${messages.map(m => `${m.role}: ${m.content.slice(0, 200)}`).join(' | ')}
JSON: {"resume": "...", "evenements_cles": ["...", "..."]}`;

  try {
    const response = await anthropic.messages.create({
      model: 'claude-sonnet-4-20250514',
      max_tokens: 300,
      messages: [{ role: 'user', content: prompt }]
    });

    let content = response.content[0].text.trim();
    if (content.startsWith('```')) content = content.replace(/```json?|```/g, '').trim();
    const parsed = JSON.parse(content);

    await supabase.from('cycle_resumes').upsert({
      partie_id: partieId, cycle, jour: gameState?.partie?.jour, date_jeu: gameState?.partie?.date_jeu,
      resume: parsed.resume, evenements_cles: parsed.evenements_cles || []
    });
    return parsed;
  } catch (e) {
    console.error('Erreur résumé:', e);
    return null;
  }
}

function buildConversationContext(conversationData, gameState, userMessage) {
  const { currentCycleMessages, previousCycleMessages, cycleResumes } = conversationData;
  let context = '';

  if (cycleResumes.length > 0) {
    context += '=== RÉSUMÉS CYCLES ===\n';
    for (const r of cycleResumes) {
      context += `[C${r.cycle}] ${r.resume}\n`;
    }
    context += '\n';
  }

  context += '=== ÉTAT ===\n' + JSON.stringify(gameState, null, 1) + '\n\n';

  if (previousCycleMessages.length > 0) {
    context += '=== FIN CYCLE PRÉCÉDENT ===\n';
    for (const m of previousCycleMessages.slice(-2)) {
      context += `${m.role}: ${m.content.slice(0, 300)}\n`;
    }
  }

  if (currentCycleMessages.length > 0) {
    context += '=== CYCLE ACTUEL ===\n';
    for (const m of currentCycleMessages.slice(-4)) {
      context += `${m.role}: ${m.content}\n`;
    }
  }

  context += '=== ACTION ===\n' + userMessage;
  return context;
}

async function saveGameState(partieId, state) {
  const { partie, valentin, ia, contexte, pnj, arcs, historique, aVenir, lieux, horsChamp } = state;

  const batch1 = [];
  if (partie) batch1.push(supabase.from('parties').update({ cycle_actuel: partie.cycle_actuel, jour: partie.jour, date_jeu: partie.date_jeu, heure: partie.heure }).eq('id', partieId));
  if (valentin) batch1.push(supabase.from('valentin').upsert({ ...valentin, partie_id: partieId }));
  if (ia) batch1.push(supabase.from('ia_personnelle').upsert({ ...ia, partie_id: partieId }));
  if (contexte) batch1.push(supabase.from('contexte').upsert({ ...contexte, partie_id: partieId }));
  await Promise.all(batch1);

  const batch2 = [];
  if (pnj?.length > 0) {
    for (const p of pnj.filter(p => p.id)) batch2.push(supabase.from('pnj').update(p).eq('id', p.id));
    const newPnj = pnj.filter(p => !p.id).map(p => ({ ...p, partie_id: partieId }));
    if (newPnj.length > 0) batch2.push(supabase.from('pnj').insert(newPnj));
  }
  if (arcs?.length > 0) {
    for (const a of arcs.filter(a => a.id)) batch2.push(supabase.from('arcs').update(a).eq('id', a.id));
    const newArcs = arcs.filter(a => !a.id).map(a => ({ ...a, partie_id: partieId }));
    if (newArcs.length > 0) batch2.push(supabase.from('arcs').insert(newArcs));
  }
  if (historique?.length > 0) {
    const newHist = historique.filter(h => !h.id).map(h => ({ ...h, partie_id: partieId }));
    if (newHist.length > 0) batch2.push(supabase.from('historique').insert(newHist));
  }
  if (aVenir?.length > 0) {
    for (const av of aVenir.filter(av => av.id)) batch2.push(supabase.from('a_venir').update(av).eq('id', av.id));
    const newAv = aVenir.filter(av => !av.id).map(av => ({ ...av, partie_id: partieId }));
    if (newAv.length > 0) batch2.push(supabase.from('a_venir').insert(newAv));
  }
  if (lieux?.length > 0) {
    const newLieux = lieux.filter(l => !l.id).map(l => ({ ...l, partie_id: partieId }));
    if (newLieux.length > 0) batch2.push(supabase.from('lieux').insert(newLieux));
  }
  if (horsChamp?.length > 0) {
    const newHc = horsChamp.filter(hc => !hc.id).map(hc => ({ ...hc, partie_id: partieId }));
    if (newHc.length > 0) batch2.push(supabase.from('hors_champ').insert(newHc));
  }
  if (batch2.length > 0) await Promise.all(batch2);
}

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

async function createNewGame() {
  const { data: partie, error } = await supabase.from('parties').insert({ nom: 'Nouvelle partie', cycle_actuel: 1, active: true }).select().single();
  if (error) throw error;
  await Promise.all([
    supabase.from('valentin').insert({ partie_id: partie.id }),
    supabase.from('ia_personnelle').insert({ partie_id: partie.id }),
    supabase.from('contexte').insert({ partie_id: partie.id })
  ]);
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
    try {
      return Response.json({ partieId: await createNewGame() });
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
      await supabase.from('parties').update({ nom: newName }).eq('id', partieId);
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

    const { data: allMessages } = await supabase.from('chat_messages').select('id, created_at').eq('partie_id', partieId).order('created_at', { ascending: true });
    if (!allMessages || fromIndex >= allMessages.length) return Response.json({ success: true });

    const toDelete = allMessages.slice(fromIndex).map(m => m.id);
    if (toDelete.length > 0) await supabase.from('chat_messages').delete().in('id', toDelete);
    return Response.json({ success: true, deleted: toDelete.length });
  } catch (e) {
    return Response.json({ error: e.message }, { status: 500 });
  }
}

export async function POST(request) {
  try {
    const { message, partieId, gameState } = await request.json();
    const currentCycle = gameState?.partie?.cycle_actuel || gameState?.cycle || 1;

    let contextMessage;
    if (partieId && gameState?.partie) {
      const conversationData = await loadConversationContext(partieId, currentCycle);
      contextMessage = buildConversationContext(conversationData, gameState, message);
    } else {
      contextMessage = 'Nouvelle partie. Lance le jeu. Génère tout.';
    }

    const { readable, writable } = new TransformStream();
    const writer = writable.getWriter();
    const encoder = new TextEncoder();

    (async () => {
      let fullContent = '', parsed = null, displayText = '';

      try {
        const streamResponse = await anthropic.messages.stream({
          model: 'claude-sonnet-4-20250514',
          max_tokens: 8192,
          system: SYSTEM_PROMPT,
          messages: [{ role: 'user', content: contextMessage }]
        });

        for await (const event of streamResponse) {
          if (event.type === 'content_block_delta' && event.delta?.text) {
            fullContent += event.delta.text;
            await writer.write(encoder.encode(`data: ${JSON.stringify({ type: 'chunk', content: event.delta.text })}\n\n`));
          }
        }

        // Vérifier si tronqué
        const finalMessage = await streamResponse.finalMessage();
        if (finalMessage.stop_reason === 'max_tokens') {
          console.warn('⚠️ Réponse tronquée!', finalMessage.usage);
        }
        console.log('Usage:', finalMessage.usage);

        // Parser le JSON
        parsed = extractJSON(fullContent);

        if (parsed) {
          displayText = '';
          if (parsed.heure) displayText += `[${parsed.heure}] `;
          if (parsed.narratif) displayText += parsed.narratif;
          if (parsed.choix?.length > 0) {
            displayText += '\n\n' + parsed.choix.map((c, i) => `${i + 1}. ${c}`).join('\n');
          }
        } else {
          console.error('JSON non parsable, fallback texte brut');
          displayText = fullContent.replace(/```json[\s\S]*?```/g, '').replace(/\{[\s\S]*\}$/g, '').trim() || "Erreur de génération. Réessaie.";
        }

        const cycleForSave = parsed?.state?.cycle || currentCycle;

        await writer.write(encoder.encode(`data: ${JSON.stringify({ type: 'done', displayText, state: parsed?.state, heure: parsed?.heure })}\n\n`));

        // Sauvegarder messages
        if (partieId) {
          await supabase.from('chat_messages').insert({ partie_id: partieId, role: 'user', content: message, cycle: cycleForSave });
          await supabase.from('chat_messages').insert({ partie_id: partieId, role: 'assistant', content: displayText, cycle: cycleForSave });
        }

        await writer.write(encoder.encode(`data: ${JSON.stringify({ type: 'saved' })}\n\n`));

      } catch (error) {
        console.error('Streaming error:', error);
        try { await writer.write(encoder.encode(`data: ${JSON.stringify({ type: 'error', error: error.message })}\n\n`)); } catch (e) {}
      } finally {
        try { await writer.close(); } catch (e) {}
      }

      // Sauvegarde state en arrière-plan
      if (partieId && parsed?.state) {
        saveGameState(partieId, {
          partie: { cycle_actuel: parsed.state.cycle, jour: parsed.state.jour, date_jeu: parsed.state.date_jeu, heure: parsed.heure },
          valentin: parsed.state.valentin, ia: parsed.state.ia, contexte: parsed.state.contexte,
          pnj: parsed.state.pnj, arcs: parsed.state.arcs, historique: parsed.state.historique,
          aVenir: parsed.state.a_venir, lieux: parsed.state.lieux, horsChamp: parsed.state.hors_champ
        }).catch(console.error);
      }

      // Résumé si changement de cycle
      if (partieId && parsed && (parsed.state?.cycle || currentCycle) > currentCycle) {
        supabase.from('chat_messages').select('role, content').eq('partie_id', partieId).eq('cycle', currentCycle).order('created_at', { ascending: true })
          .then(({ data }) => data && generateCycleResume(partieId, currentCycle, data, gameState))
          .catch(console.error);
      }
    })();

    return new Response(readable, {
      headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache, no-transform', 'Connection': 'keep-alive', 'X-Accel-Buffering': 'no' }
    });

  } catch (e) {
    console.error('Erreur:', e);
    return Response.json({ error: e.message }, { status: 500 });
  }
}
