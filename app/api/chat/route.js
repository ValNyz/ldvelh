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
  const [currentCycleRes, previousCycleRes, cycleResumesRes] = await Promise.all([
    supabase
      .from('chat_messages')
      .select('role, content, cycle, created_at')
      .eq('partie_id', partieId)
      .eq('cycle', currentCycle)
      .order('created_at', { ascending: true }),
    supabase
      .from('chat_messages')
      .select('role, content, cycle, created_at')
      .eq('partie_id', partieId)
      .eq('cycle', currentCycle - 1)
      .order('created_at', { ascending: false })
      .limit(5),
    supabase
      .from('cycle_resumes')
      .select('cycle, jour, date_jeu, resume, evenements_cles, relations_modifiees')
      .eq('partie_id', partieId)
      .lt('cycle', currentCycle - 1)
      .order('cycle', { ascending: false })
      .limit(5)
  ]);

  return {
    currentCycleMessages: currentCycleRes.data || [],
    previousCycleMessages: (previousCycleRes.data || []).reverse(),
    cycleResumes: (cycleResumesRes.data || []).reverse()
  };
}

// Charger tous les messages chat (pour l'affichage)
async function loadChatMessages(partieId) {
  const { data, error } = await supabase
    .from('chat_messages')
    .select('role, content, cycle, created_at')
    .eq('partie_id', partieId)
    .order('created_at', { ascending: true });
  
  if (error) {
    console.error('Erreur chargement messages:', error);
    return [];
  }
  
  console.log(`Loaded ${data?.length || 0} messages for partie ${partieId}`);
  return data || [];
}

// Générer un résumé de cycle via Claude (non-streaming)
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

  context += '=== ÉTAT ACTUEL ===\n';
  context += JSON.stringify(gameState, null, 2);
  context += '\n\n';

  if (previousCycleMessages.length > 0) {
    context += '=== FIN DU CYCLE PRÉCÉDENT ===\n';
    for (const m of previousCycleMessages) {
      context += `${m.role.toUpperCase()}: ${m.content}\n\n`;
    }
  }

  if (currentCycleMessages.length > 0) {
    context += '=== CYCLE ACTUEL ===\n';
    for (const m of currentCycleMessages) {
      context += `${m.role.toUpperCase()}: ${m.content}\n\n`;
    }
  }

  context += '=== ACTION DU JOUEUR ===\n';
  context += userMessage;

  return context;
}

// Sauvegarder l'état - VERSION BATCH
async function saveGameState(partieId, state) {
  const { partie, valentin, ia, contexte, pnj, arcs, historique, aVenir, lieux, horsChamp } = state;

  // Batch 1: Updates simples (upsert uniques)
  const batch1 = [];
  
  if (partie) {
    batch1.push(
      supabase.from('parties').update({
        cycle_actuel: partie.cycle_actuel,
        jour: partie.jour,
        date_jeu: partie.date_jeu,
        heure: partie.heure
      }).eq('id', partieId)
    );
  }

  if (valentin) {
    batch1.push(supabase.from('valentin').upsert({ ...valentin, partie_id: partieId }));
  }

  if (ia) {
    batch1.push(supabase.from('ia_personnelle').upsert({ ...ia, partie_id: partieId }));
  }

  if (contexte) {
    batch1.push(supabase.from('contexte').upsert({ ...contexte, partie_id: partieId }));
  }

  await Promise.all(batch1);

  // Batch 2: Arrays (PNJ, arcs, etc.)
  const batch2 = [];

  // PNJ - séparer updates et inserts
  if (pnj && pnj.length > 0) {
    const pnjToUpdate = pnj.filter(p => p.id);
    const pnjToInsert = pnj.filter(p => !p.id).map(p => ({ ...p, partie_id: partieId }));
    
    if (pnjToUpdate.length > 0) {
      for (const p of pnjToUpdate) {
        batch2.push(supabase.from('pnj').update(p).eq('id', p.id));
      }
    }
    if (pnjToInsert.length > 0) {
      batch2.push(supabase.from('pnj').insert(pnjToInsert));
    }
  }

  // Arcs
  if (arcs && arcs.length > 0) {
    const arcsToUpdate = arcs.filter(a => a.id);
    const arcsToInsert = arcs.filter(a => !a.id).map(a => ({ ...a, partie_id: partieId }));
    
    if (arcsToUpdate.length > 0) {
      for (const a of arcsToUpdate) {
        batch2.push(supabase.from('arcs').update(a).eq('id', a.id));
      }
    }
    if (arcsToInsert.length > 0) {
      batch2.push(supabase.from('arcs').insert(arcsToInsert));
    }
  }

  // Historique - insert du nouveau uniquement
  if (historique && historique.length > 0) {
    const newHistorique = historique.filter(h => !h.id).map(h => ({ ...h, partie_id: partieId }));
    if (newHistorique.length > 0) {
      batch2.push(supabase.from('historique').insert(newHistorique));
    }
  }

  // A venir
  if (aVenir && aVenir.length > 0) {
    const aVenirToUpdate = aVenir.filter(av => av.id);
    const aVenirToInsert = aVenir.filter(av => !av.id).map(av => ({ ...av, partie_id: partieId }));
    
    if (aVenirToUpdate.length > 0) {
      for (const av of aVenirToUpdate) {
        batch2.push(supabase.from('a_venir').update(av).eq('id', av.id));
      }
    }
    if (aVenirToInsert.length > 0) {
      batch2.push(supabase.from('a_venir').insert(aVenirToInsert));
    }
  }

  // Lieux - insert nouveaux uniquement
  if (lieux && lieux.length > 0) {
    const newLieux = lieux.filter(l => !l.id).map(l => ({ ...l, partie_id: partieId }));
    if (newLieux.length > 0) {
      batch2.push(supabase.from('lieux').insert(newLieux));
    }
  }

  // Hors champ - insert nouveaux uniquement
  if (horsChamp && horsChamp.length > 0) {
    const newHorsChamp = horsChamp.filter(hc => !hc.id).map(hc => ({ ...hc, partie_id: partieId }));
    if (newHorsChamp.length > 0) {
      batch2.push(supabase.from('hors_champ').insert(newHorsChamp));
    }
  }

  if (batch2.length > 0) {
    await Promise.all(batch2);
  }
}

// Supprimer une partie et toutes ses données
async function deleteGame(partieId) {
  // Toutes les suppressions en parallèle (les FK sont en CASCADE normalement)
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

// Renommer une partie
async function renameGame(partieId, newName) {
  await supabase.from('parties').update({ nom: newName }).eq('id', partieId);
}

// Créer nouvelle partie
async function createNewGame() {
  try {
    const { data: partie, error: partieError } = await supabase
      .from('parties')
      .insert({ nom: 'Nouvelle partie', cycle_actuel: 1, active: true })
      .select()
      .single();
    
    if (partieError) {
      console.error('Erreur création partie:', partieError);
      throw partieError;
    }

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
    
    if (!partieId) {
      return Response.json({ error: 'partieId manquant' }, { status: 400 });
    }

    const { data: allMessages } = await supabase
      .from('chat_messages')
      .select('id, created_at')
      .eq('partie_id', partieId)
      .order('created_at', { ascending: true });

    if (!allMessages || fromIndex >= allMessages.length) {
      return Response.json({ success: true });
    }

    const messagesToDelete = allMessages.slice(fromIndex).map(m => m.id);
    
    if (messagesToDelete.length > 0) {
      await supabase
        .from('chat_messages')
        .delete()
        .in('id', messagesToDelete);
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

    // Charger le contexte conversationnel si partie existante avec gameState
    let contextMessage;
    if (partieId && gameState && gameState.partie) {
      const conversationData = await loadConversationContext(partieId, currentCycle);
      contextMessage = buildConversationContext(conversationData, gameState, message);
    } else {
      contextMessage = 'Nouvelle partie. Lance le jeu. Génère tout au lancement.';
    }

    // Créer un TransformStream pour le SSE
    const { readable, writable } = new TransformStream();
    const writer = writable.getWriter();
    const encoder = new TextEncoder();

    // Lancer le traitement en arrière-plan
    (async () => {
      let fullContent = '';

      try {
        // Appel Claude avec streaming
        const streamResponse = await anthropic.messages.stream({
          model: 'claude-sonnet-4-20250514',
          max_tokens: 4096,
          system: SYSTEM_PROMPT,
          messages: [{ role: 'user', content: contextMessage }]
        });

        // Écouter les événements de texte
        for await (const event of streamResponse) {
          if (event.type === 'content_block_delta' && event.delta?.text) {
            const chunk = event.delta.text;
            fullContent += chunk;
            
            // Envoyer le chunk au client
            await writer.write(encoder.encode(`data: ${JSON.stringify({ type: 'chunk', content: chunk })}\n\n`));
          }
        }

        // Traitement final une fois le stream terminé
        let parsed = null;
        let displayText = fullContent;

        try {
          let cleanContent = fullContent.trim();
          
          // Chercher le dernier bloc JSON valide dans la réponse
          const jsonStartIndex = cleanContent.lastIndexOf('\n{');
          const jsonStartIndex2 = cleanContent.indexOf('{');
          
          let jsonContent = cleanContent;
          
          // Si le contenu ne commence pas par {, chercher le JSON à la fin
          if (jsonStartIndex > 0) {
            jsonContent = cleanContent.slice(jsonStartIndex + 1).trim();
          } else if (jsonStartIndex2 === 0) {
            // Le contenu commence par { - c'est du JSON pur
            if (cleanContent.startsWith('```json')) cleanContent = cleanContent.slice(7);
            if (cleanContent.startsWith('```')) cleanContent = cleanContent.slice(3);
            if (cleanContent.endsWith('```')) cleanContent = cleanContent.slice(0, -3);
            jsonContent = cleanContent.trim();
          }
          
          parsed = JSON.parse(jsonContent);

          // Construire le texte d'affichage à partir du JSON
          displayText = '';
          if (parsed.heure) displayText += `[${parsed.heure}] `;
          if (parsed.narratif) displayText += parsed.narratif;
          if (parsed.choix && parsed.choix.length > 0) {
            displayText += '\n\n' + parsed.choix.map((c, i) => `${i + 1}. ${c}`).join('\n');
          }
        } catch (e) {
          // Si pas JSON valide, garder le texte brut mais nettoyer le JSON visible
          console.error('Erreur parsing JSON:', e.message);
          
          // Essayer de nettoyer le texte brut (enlever le JSON à la fin)
          const jsonStartIndex = fullContent.lastIndexOf('\n{');
          if (jsonStartIndex > 0) {
            displayText = fullContent.slice(0, jsonStartIndex).trim();
          }
          
          parsed = null;
        }

        // Déterminer le cycle à utiliser pour la sauvegarde
        const cycleForSave = parsed?.state?.cycle || currentCycle;

        // Envoyer le message final avec les données parsées AVANT les sauvegardes
        await writer.write(encoder.encode(`data: ${JSON.stringify({ 
          type: 'done', 
          displayText,
          state: parsed?.state,
          heure: parsed?.heure
        })}\n\n`));

        // === SAUVEGARDES ===
        
        // Sauvegarder les messages (PRIORITAIRE - on attend juste ça)
        if (partieId) {
          console.log(`Saving messages for partie ${partieId}, cycle ${cycleForSave}`);
          
          await supabase.from('chat_messages').insert({
            partie_id: partieId, 
            role: 'user', 
            content: message, 
            cycle: cycleForSave
          });
          
          await supabase.from('chat_messages').insert({
            partie_id: partieId, 
            role: 'assistant', 
            content: displayText, 
            cycle: cycleForSave
          });
        }

        // Notifier le client que les messages sont sauvés - IL PEUT RÉPONDRE
        await writer.write(encoder.encode(`data: ${JSON.stringify({ type: 'saved' })}\n\n`));
        await writer.close();

        // === LE RESTE EN VRAI ARRIÈRE-PLAN (après fermeture du stream) ===
        
        // Sauvegarder l'état (non-bloquant)
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
          }).catch(console.error);
        }

        // Générer résumé si changement de cycle (non-bloquant)
        if (partieId && parsed && cycleForSave > currentCycle) {
          supabase
            .from('chat_messages')
            .select('role, content')
            .eq('partie_id', partieId)
            .eq('cycle', currentCycle)
            .order('created_at', { ascending: true })
            .then(({ data: cycleMessages }) => {
              if (cycleMessages) {
                generateCycleResume(partieId, currentCycle, cycleMessages, gameState).catch(console.error);
              }
            })
            .catch(console.error);
        }

      } catch (error) {
        console.error('Streaming error:', error);
        try {
          await writer.write(encoder.encode(`data: ${JSON.stringify({ type: 'error', error: error.message })}\n\n`));
          await writer.close();
        } catch (e) {
          // Writer peut être déjà fermé
        }
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
    console.error('Erreur:', e);
    return Response.json({ error: e.message }, { status: 500 });
  }
}
