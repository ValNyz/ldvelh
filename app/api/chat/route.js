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

/**
 * Tente de réparer un JSON mal formé
 */
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
  } catch (e) {
    // Continue avec les corrections
  }
  
  // Trouver le dernier } qui ferme correctement le JSON
  let lastValidIndex = -1;
  let braceCount = 0;
  let inString = false;
  let escapeNext = false;
  
  for (let i = 0; i < fixed.length; i++) {
    const char = fixed[i];
    
    if (escapeNext) {
      escapeNext = false;
      continue;
    }
    
    if (char === '\\' && inString) {
      escapeNext = true;
      continue;
    }
    
    if (char === '"' && !escapeNext) {
      inString = !inString;
      continue;
    }
    
    if (!inString) {
      if (char === '{') braceCount++;
      if (char === '}') {
        braceCount--;
        if (braceCount === 0) {
          lastValidIndex = i;
        }
      }
    }
  }
  
  if (lastValidIndex > 0) {
    try {
      return JSON.parse(fixed.slice(0, lastValidIndex + 1));
    } catch (e) {
      // Continue
    }
  }
  
  // Compter et fermer les accolades/crochets manquants
  let openBraces = 0;
  let openBrackets = 0;
  inString = false;
  escapeNext = false;
  
  for (let i = 0; i < fixed.length; i++) {
    const char = fixed[i];
    
    if (escapeNext) {
      escapeNext = false;
      continue;
    }
    
    if (char === '\\' && inString) {
      escapeNext = true;
      continue;
    }
    
    if (char === '"') {
      inString = !inString;
      continue;
    }
    
    if (!inString) {
      if (char === '{') openBraces++;
      if (char === '}') openBraces--;
      if (char === '[') openBrackets++;
      if (char === ']') openBrackets--;
    }
  }
  
  // Si on est dans une string non fermée, fermer la string
  if (inString) {
    fixed += '"';
  }
  
  // Fermer les brackets et braces manquants
  while (openBrackets > 0) {
    fixed += ']';
    openBrackets--;
  }
  while (openBraces > 0) {
    fixed += '}';
    openBraces--;
  }
  
  try {
    return JSON.parse(fixed);
  } catch (e) {
    // Continue
  }
  
  // Corrections supplémentaires
  fixed = fixed.replace(/,(\s*[}\]])/g, '$1'); // Virgule trailing
  fixed = fixed.replace(/:\s*([}\]])/g, ': null$1'); // Valeur manquante
  fixed = fixed.replace(/:\s*,/g, ': null,'); // Valeur manquante avant virgule
  
  try {
    return JSON.parse(fixed);
  } catch (e) {
    console.error('JSON repair failed:', e.message);
    return null;
  }
}

/**
 * Extrait le JSON de la réponse Claude (peut être mélangé avec du texte)
 */
function extractJSON(content) {
  if (!content) return null;
  
  // Méthode 1: JSON pur (commence par {)
  if (content.trim().startsWith('{')) {
    const result = tryFixJSON(content);
    if (result) return result;
  }
  
  // Méthode 2: JSON après du texte (cherche \n{)
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

// ============================================================================
// FONCTIONS DE CHARGEMENT DES DONNÉES
// ============================================================================

/**
 * Charge l'état complet d'une partie depuis Supabase
 */
async function loadGameState(partieId) {
  const [
    partie,
    valentin,
    ia,
    contexte,
    pnj,
    arcs,
    historique,
    aVenir,
    lieux,
    horsChamp
  ] = await Promise.all([
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

/**
 * Charge le contexte conversationnel pour Claude
 */
async function loadConversationContext(partieId, currentCycle) {
  const [currentCycleRes, previousCycleRes, cycleResumesRes] = await Promise.all([
    // Messages du cycle actuel
    supabase
      .from('chat_messages')
      .select('role, content, cycle, created_at')
      .eq('partie_id', partieId)
      .eq('cycle', currentCycle)
      .order('created_at', { ascending: true }),
    
    // Derniers messages du cycle précédent (limité à 3)
    supabase
      .from('chat_messages')
      .select('role, content, cycle, created_at')
      .eq('partie_id', partieId)
      .eq('cycle', currentCycle - 1)
      .order('created_at', { ascending: false })
      .limit(3),
    
    // Résumés des cycles anciens (limité à 3)
    supabase
      .from('cycle_resumes')
      .select('cycle, jour, date_jeu, resume, evenements_cles')
      .eq('partie_id', partieId)
      .lt('cycle', currentCycle - 1)
      .order('cycle', { ascending: false })
      .limit(3)
  ]);

  return {
    currentCycleMessages: currentCycleRes.data || [],
    previousCycleMessages: (previousCycleRes.data || []).reverse(),
    cycleResumes: (cycleResumesRes.data || []).reverse()
  };
}

/**
 * Charge tous les messages chat pour l'affichage
 */
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

// ============================================================================
// GÉNÉRATION DE RÉSUMÉ DE CYCLE
// ============================================================================

/**
 * Génère un résumé de cycle via Claude (non-streaming)
 */
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
    
    // Nettoyer les backticks
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

/**
 * Construit le message de contexte pour Claude
 */
function buildConversationContext(conversationData, gameState, userMessage) {
  const { currentCycleMessages, previousCycleMessages, cycleResumes } = conversationData;
  
  let context = '';

  // Résumés des cycles anciens
  if (cycleResumes.length > 0) {
    context += '=== RÉSUMÉS CYCLES PRÉCÉDENTS ===\n';
    for (const r of cycleResumes) {
      context += `[Cycle ${r.cycle}] ${r.resume}\n`;
    }
    context += '\n';
  }

  // État actuel du jeu
  context += '=== ÉTAT ACTUEL ===\n';
  context += JSON.stringify(gameState, null, 1);
  context += '\n\n';

  // Fin du cycle précédent (limité)
  if (previousCycleMessages.length > 0) {
    context += '=== FIN CYCLE PRÉCÉDENT ===\n';
    for (const m of previousCycleMessages.slice(-2)) {
      context += `${m.role.toUpperCase()}: ${m.content.slice(0, 300)}\n`;
    }
    context += '\n';
  }

  // Messages du cycle actuel (limité aux 4 derniers)
  if (currentCycleMessages.length > 0) {
    context += '=== CYCLE ACTUEL ===\n';
    for (const m of currentCycleMessages.slice(-4)) {
      context += `${m.role.toUpperCase()}: ${m.content}\n\n`;
    }
  }

  // Action du joueur
  context += '=== ACTION DU JOUEUR ===\n';
  context += userMessage;

  return context;
}

// ============================================================================
// SAUVEGARDE DE L'ÉTAT
// ============================================================================

/**
 * Sauvegarde l'état du jeu dans Supabase (version batch optimisée)
 */
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
    
    for (const p of pnjToUpdate) {
      batch2.push(supabase.from('pnj').update(p).eq('id', p.id));
    }
    if (pnjToInsert.length > 0) {
      batch2.push(supabase.from('pnj').insert(pnjToInsert));
    }
  }

  // Arcs
  if (arcs && arcs.length > 0) {
    const arcsToUpdate = arcs.filter(a => a.id);
    const arcsToInsert = arcs.filter(a => !a.id).map(a => ({ ...a, partie_id: partieId }));
    
    for (const a of arcsToUpdate) {
      batch2.push(supabase.from('arcs').update(a).eq('id', a.id));
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
    
    for (const av of aVenirToUpdate) {
      batch2.push(supabase.from('a_venir').update(av).eq('id', av.id));
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

// ============================================================================
// GESTION DES PARTIES
// ============================================================================

/**
 * Supprime une partie et toutes ses données
 */
async function deleteGame(partieId) {
  // Toutes les suppressions en parallèle
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

/**
 * Renomme une partie
 */
async function renameGame(partieId, newName) {
  await supabase.from('parties').update({ nom: newName }).eq('id', partieId);
}

/**
 * Crée une nouvelle partie
 */
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

    // Créer les enregistrements liés
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

/**
 * GET - Actions de lecture et gestion des parties
 */
export async function GET(request) {
  const { searchParams } = new URL(request.url);
  const action = searchParams.get('action');
  const partieId = searchParams.get('partieId');

  // Charger une partie
  if (action === 'load' && partieId) {
    const state = await loadGameState(partieId);
    const messages = await loadChatMessages(partieId);
    return Response.json({ state, messages });
  }

  // Lister les parties
  if (action === 'list') {
    const { data } = await supabase
      .from('parties')
      .select('id, nom, cycle_actuel, updated_at, created_at')
      .eq('active', true)
      .order('updated_at', { ascending: false });
    return Response.json({ parties: data });
  }

  // Nouvelle partie
  if (action === 'new') {
    try {
      const partieId = await createNewGame();
      return Response.json({ partieId });
    } catch (e) {
      return Response.json({ error: e.message }, { status: 500 });
    }
  }

  // Supprimer une partie
  if (action === 'delete' && partieId) {
    await deleteGame(partieId);
    return Response.json({ success: true });
  }

  // Renommer une partie
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

/**
 * DELETE - Supprimer des messages à partir d'un index
 */
export async function DELETE(request) {
  try {
    const { partieId, fromIndex } = await request.json();
    
    if (!partieId) {
      return Response.json({ error: 'partieId manquant' }, { status: 400 });
    }

    // Récupérer tous les messages triés
    const { data: allMessages } = await supabase
      .from('chat_messages')
      .select('id, created_at')
      .eq('partie_id', partieId)
      .order('created_at', { ascending: true });

    if (!allMessages || fromIndex >= allMessages.length) {
      return Response.json({ success: true });
    }

    // Supprimer à partir de l'index
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

/**
 * POST - Envoyer un message et obtenir une réponse de Claude
 */
export async function POST(request) {
  try {
    const { message, partieId, gameState } = await request.json();

    const currentCycle = gameState?.partie?.cycle_actuel || gameState?.cycle || 1;

    // Construire le contexte pour Claude
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
      let parsed = null;
      let displayText = '';

      try {
        // Appel Claude avec streaming
        const streamResponse = await anthropic.messages.stream({
          model: 'claude-sonnet-4-20250514',
          max_tokens: 8192,
          system: SYSTEM_PROMPT,
          messages: [{ role: 'user', content: contextMessage }]
        });

        // Écouter les événements de texte
        for await (const event of streamResponse) {
          if (event.type === 'content_block_delta' && event.delta?.text) {
            const chunk = event.delta.text;
            fullContent += chunk;
            
            // Envoyer le chunk au client
            await writer.write(
              encoder.encode(`data: ${JSON.stringify({ type: 'chunk', content: chunk })}\n\n`)
            );
          }
        }
        let t0 = Date.now(), t1;
        console.log('>>> 1. Stream terminé');

        // Vérifier si la réponse a été tronquée
        const finalMessage = await streamResponse.finalMessage();
        t1 = Date.now(); console.log(`>>> 2. finalMessage récupéré: +${t1 - t0}ms`); t0 = t1;
        
        if (finalMessage.stop_reason === 'max_tokens') {
          console.warn('⚠️ Réponse tronquée! max_tokens atteint');
          console.warn('Usage:', finalMessage.usage);
        } else {
          console.log('✓ Réponse complète. Usage:', finalMessage.usage);
        }

        // Parser le JSON
        parsed = extractJSON(fullContent);
        t1 = Date.now(); console.log(`>>> 3. JSON parsé: +${t1 - t0}ms`); t0 = t1;
        console.log('>>> 3b. parsed est null?', parsed === null);
        console.log('>>> 3c. parsed.heure:', parsed?.heure);
        console.log('>>> 3d. parsed.narratif length:', parsed?.narratif?.length);
        console.log('>>> 3e. parsed.choix:', parsed?.choix);
        console.log('>>> 3f. parsed.state exists?', !!parsed?.state);

        if (parsed) {
          // Construire le texte d'affichage à partir du JSON
          displayText = '';
          if (parsed.heure) displayText += `[${parsed.heure}] `;
          if (parsed.narratif) displayText += parsed.narratif;
          if (parsed.choix && parsed.choix.length > 0) {
            displayText += '\n\n' + parsed.choix.map((c, i) => `${i + 1}. ${c}`).join('\n');
          }
        } else {
          console.error('JSON non parsable, utilisation du texte brut');
          // Fallback: nettoyer le texte brut
          displayText = fullContent
            .replace(/```json[\s\S]*?```/g, '')
            .replace(/\{[\s\S]*\}$/g, '')
            .trim();
          
          if (!displayText) {
            displayText = "Une erreur s'est produite lors de la génération. Réessaie.";
          }
        }

        const cycleForSave = parsed?.state?.cycle || currentCycle;

        // Envoyer le message final avec les données parsées
        await writer.write(
          encoder.encode(`data: ${JSON.stringify({ 
            type: 'done', 
            displayText,
            state: parsed?.state,
            heure: parsed?.heure
          })}\n\n`)
        );

        // Signaler immédiatement que le client peut continuer
        await writer.write(encoder.encode(`data: ${JSON.stringify({ type: 'saved' })}\n\n`));

        // Sauvegarder les messages en arrière-plan (non-bloquant)
        if (partieId) {
          (async () => {
            try {
              const saveStart = Date.now();
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
              console.log(`Messages saved in ${Date.now() - saveStart}ms`);
            } catch (err) {
              console.error('Erreur sauvegarde messages:', err);
            }
          })();
        }

      } catch (error) {
        console.error('Streaming error:', error);
        try {
          await writer.write(
            encoder.encode(`data: ${JSON.stringify({ type: 'error', error: error.message })}\n\n`)
          );
        } catch (e) {
          // Writer peut être déjà fermé
        }
      } finally {
        // Fermer le stream
        try {
          await writer.close();
        } catch (e) {
          // Déjà fermé
        }
      }
      
      // === TÂCHES EN ARRIÈRE-PLAN (après fermeture du stream) ===
      
      // Sauvegarder l'état du jeu (non-bloquant)
      if (partieId && parsed?.state) {
        saveGameState(partieId, {
          partie: { 
            cycle_actuel: parsed.state.cycle, 
            jour: parsed.state.jour, 
            date_jeu: parsed.state.date_jeu, 
            heure: parsed.heure 
          },
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
      const cycleForSave = parsed?.state?.cycle || currentCycle;
      if (partieId && parsed && cycleForSave > currentCycle) {
        supabase
          .from('chat_messages')
          .select('role, content')
          .eq('partie_id', partieId)
          .eq('cycle', currentCycle)
          .order('created_at', { ascending: true })
          .then(({ data: cycleMessages }) => {
            if (cycleMessages) {
              generateCycleResume(partieId, currentCycle, cycleMessages, gameState)
                .catch(err => console.error('Erreur génération résumé:', err));
            }
          })
          .catch(err => console.error('Erreur chargement messages cycle:', err));
      }
    })();

    // Retourner le stream SSE
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
