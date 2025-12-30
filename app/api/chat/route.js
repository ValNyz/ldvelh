import Anthropic from '@anthropic-ai/sdk';
import { createClient } from '@supabase/supabase-js';
import { SYSTEM_PROMPT_INIT, SYSTEM_PROMPT_GAME } from '../../../lib/prompt';

export const dynamic = 'force-dynamic';

const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL,
  process.env.SUPABASE_SERVICE_KEY
);

// ============================================
// APPLY DELTA - Applique les changements au state
// ============================================

function applyDelta(currentState, delta) {
  if (!delta || Object.keys(delta).length === 0) {
    return { newState: currentState, changelog: [] };
  }

  const newState = JSON.parse(JSON.stringify(currentState));
  const changelog = [];

  for (const [key, value] of Object.entries(delta)) {
    
    // === Stats Valentin ===
    if (key.startsWith('valentin.')) {
      const stat = key.replace('valentin.', '');
      const oldVal = newState.valentin?.[stat];
      let newVal = value;
      
      // Validation des bornes
      if (['energie', 'moral', 'sante'].includes(stat)) {
        newVal = Math.max(0, Math.min(5, value));
      }
      if (stat === 'credits') {
        newVal = Math.max(0, value);
      }
      
      if (!newState.valentin) newState.valentin = {};
      newState.valentin[stat] = newVal;
      changelog.push(`${stat}: ${oldVal} → ${newVal}`);
    }
    
    // === Heure ===
    else if (key === 'heure') {
      newState.heure = value;
      changelog.push(`heure: ${value}`);
    }
    
    // === Nouveau cycle ===
    else if (key === 'nouveau_cycle') {
      newState.cycle = value.cycle;
      newState.jour = value.jour;
      newState.date_jeu = value.date_jeu;
      newState.heure = '08h00';
      changelog.push(`nouveau cycle ${value.cycle}: ${value.jour} ${value.date_jeu}`);
    }
    
    // === PNJ existant ===
    else if (key.startsWith('pnj.')) {
      const parts = key.split('.');
      const pnjName = parts[1];
      const prop = parts[2];
      
      if (!newState.pnj) newState.pnj = [];
      const pnj = newState.pnj.find(p => p.nom === pnjName);
      
      if (pnj) {
        const oldVal = pnj[prop];
        let newVal = value;
        
        // Validation
        if (prop === 'relation') {
          newVal = Math.max(-5, Math.min(10, value));
        }
        if (prop === 'etape_romantique') {
          // On ne peut avancer que de 1 max
          const maxEtape = Math.min(7, (pnj.etape_romantique || 0) + 1);
          newVal = Math.max(0, Math.min(maxEtape, value));
        }
        
        pnj[prop] = newVal;
        changelog.push(`${pnjName}.${prop}: ${oldVal} → ${newVal}`);
      }
    }
    
    // === Nouveau PNJ ===
    else if (key === 'nouveau_pnj') {
      if (!newState.pnj) newState.pnj = [];
      
      if (!newState.pnj.find(p => p.nom === value.nom)) {
        newState.pnj.push({
          nom: value.nom,
          metier: value.metier || 'Inconnu',
          traits: value.traits || [],
          description: value.description || '',
          relation: 0,
          disposition: 'neutre',
          etape_romantique: 0
        });
        changelog.push(`nouveau PNJ: ${value.nom}`);
      }
    }
    
    // === Hors-champ ===
    else if (key === 'hors_champ') {
      if (!newState.horsChamp) newState.horsChamp = [];
      newState.horsChamp.push({
        cycle: newState.cycle || 1,
        description: value
      });
      // Garder max 20
      if (newState.horsChamp.length > 20) {
        newState.horsChamp = newState.horsChamp.slice(-20);
      }
      changelog.push(`hors-champ ajouté`);
    }
    
    // === Historique ===
    else if (key === 'historique') {
      if (!newState.historique) newState.historique = [];
      newState.historique.push({
        cycle: newState.cycle || 1,
        description: value
      });
      if (newState.historique.length > 50) {
        newState.historique = newState.historique.slice(-50);
      }
      changelog.push(`historique ajouté`);
    }
    
    // === Nouveau lieu ===
    else if (key === 'nouveau_lieu') {
      if (!newState.lieux) newState.lieux = [];
      if (!newState.lieux.find(l => l.nom === value.nom)) {
        newState.lieux.push({
          nom: value.nom,
          type: value.type || 'autre',
          description: value.description || ''
        });
        changelog.push(`nouveau lieu: ${value.nom}`);
      }
    }
    
    // === Arc narratif ===
    else if (key.startsWith('arc.')) {
      const parts = key.split('.');
      const arcTitre = parts[1];
      const prop = parts[2];
      
      if (!newState.arcs) newState.arcs = [];
      let arc = newState.arcs.find(a => a.titre === arcTitre);
      
      if (arc) {
        const oldVal = arc[prop];
        if (prop === 'progression') {
          arc[prop] = Math.max(0, Math.min(10, value));
          arc.actif = true;
        } else {
          arc[prop] = value;
        }
        changelog.push(`arc "${arcTitre}".${prop}: ${oldVal} → ${value}`);
      }
    }
  }

  return { newState, changelog };
}

// ============================================
// BUILD INITIAL STATE - Construit le state depuis l'init
// ============================================

function buildInitialState(init, heure) {
  return {
    cycle: 1,
    jour: 'Lundi',
    date_jeu: '15 mars 2247',
    heure: heure || '08h00',
    
    valentin: {
      energie: 4,
      moral: 3,
      sante: 5,
      credits: 1400,
      competences: {
        informatique: 5,
        systemes: 4,
        social: 2,
        cuisine: 3,
        bricolage: 3,
        medical: 1
      },
      traits: ['Introverti', 'Maladroit en amour', 'Drôle par défense', 'Curieux', 'Romantique malgré lui'],
      hobbies: init.valentin?.hobbies || ['Cuisine'],
      poste: init.valentin?.poste || '',
      raison_depart: init.valentin?.raison_depart || ''
    },
    
    ia: {
      nom: init.ia?.nom || 'Nova',
      traits: init.ia?.traits || ['Sarcastique', 'Pragmatique']
    },
    
    contexte: {
      station_nom: init.contexte?.station_nom || '',
      station_type: init.contexte?.station_type || '',
      orbite: init.contexte?.orbite || '',
      population: init.contexte?.population || 0,
      ambiance: init.contexte?.ambiance || '',
      employeur_nom: init.employeur?.nom || '',
      employeur_type: init.employeur?.type || '',
      employeur_description: init.employeur?.description || ''
    },
    
    pnj: [{
      nom: 'Justine Lépicier',
      relation: 0,
      disposition: 'neutre',
      traits: init.justine?.traits || [],
      metier: init.justine?.metier || '',
      arc: init.justine?.arc || '',
      domicile: init.justine?.domicile || '',
      etape_romantique: 0,
      stat_social: 4,
      stat_travail: 2,
      stat_sante: 2
    }],
    
    lieux: init.lieux || [],
    
    arcs: (init.arcs || []).map(a => ({
      titre: a.titre,
      type: a.type,
      description: a.description,
      progression: 0,
      actif: false
    })),
    
    historique: [],
    horsChamp: [],
    aVenir: []
  };
}

// ============================================
// PARSING JSON ROBUSTE
// ============================================

function tryFixJSON(jsonStr) {
  let fixed = jsonStr.trim();
  
  // Enlever les backticks markdown
  if (fixed.startsWith('```json')) fixed = fixed.slice(7);
  if (fixed.startsWith('```')) fixed = fixed.slice(3);
  if (fixed.endsWith('```')) fixed = fixed.slice(0, -3);
  fixed = fixed.trim();
  
  // Trouver le premier {
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
  
  // Compter et réparer les accolades/crochets
  let braces = 0, brackets = 0, inString = false, escape = false;
  
  for (let i = 0; i < fixed.length; i++) {
    const c = fixed[i];
    if (escape) { escape = false; continue; }
    if (c === '\\' && inString) { escape = true; continue; }
    if (c === '"') { inString = !inString; continue; }
    if (!inString) {
      if (c === '{') braces++;
      if (c === '}') braces--;
      if (c === '[') brackets++;
      if (c === ']') brackets--;
    }
  }
  
  // Fermer les strings non fermées
  if (inString) fixed += '"';
  
  // Fermer les brackets et braces manquants
  while (brackets > 0) { fixed += ']'; brackets--; }
  while (braces > 0) { fixed += '}'; braces--; }
  
  // Retirer virgules trailing
  fixed = fixed.replace(/,(\s*[}\]])/g, '$1');
  
  try {
    return JSON.parse(fixed);
  } catch (e) {
    console.error('JSON non réparable:', e.message);
    return null;
  }
}

// ============================================
// CHARGEMENT STATE COMPLET
// ============================================

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
    cycle: partie.data?.cycle_actuel || 1,
    jour: partie.data?.jour,
    date_jeu: partie.data?.date_jeu,
    heure: partie.data?.heure || '08h00',
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

// ============================================
// CHARGEMENT CONTEXTE CONVERSATIONNEL
// ============================================

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

// ============================================
// CHARGEMENT MESSAGES CHAT
// ============================================

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
  
  return data || [];
}

// ============================================
// GÉNÉRATION RÉSUMÉ DE CYCLE
// ============================================

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
      jour: gameState?.jour,
      date_jeu: gameState?.date_jeu,
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

// ============================================
// CONSTRUCTION CONTEXTE POUR CLAUDE
// ============================================

function buildConversationContext(conversationData, gameState, userMessage) {
  const { currentCycleMessages, previousCycleMessages, cycleResumes } = conversationData;
  
  let context = '';

  // Résumés des cycles passés
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

  // État actuel (version allégée pour le contexte)
  context += '=== ÉTAT ACTUEL ===\n';
  context += JSON.stringify({
    cycle: gameState.cycle,
    jour: gameState.jour,
    date_jeu: gameState.date_jeu,
    heure: gameState.heure,
    valentin: {
      energie: gameState.valentin?.energie,
      moral: gameState.valentin?.moral,
      sante: gameState.valentin?.sante,
      credits: gameState.valentin?.credits
    },
    pnj: gameState.pnj?.map(p => ({
      nom: p.nom,
      relation: p.relation,
      disposition: p.disposition,
      etape_romantique: p.etape_romantique
    })),
    lieux_connus: gameState.lieux?.map(l => l.nom),
    arcs_actifs: gameState.arcs?.filter(a => a.actif || a.progression > 0).map(a => ({
      titre: a.titre,
      progression: a.progression
    }))
  }, null, 2);
  context += '\n\n';

  // Hors-champ récent
  if (gameState.horsChamp?.length > 0) {
    context += '=== HORS-CHAMP RÉCENT ===\n';
    context += gameState.horsChamp.slice(-5).map(h => `[Cycle ${h.cycle}] ${h.description}`).join('\n');
    context += '\n\n';
  }

  // Fin du cycle précédent
  if (previousCycleMessages.length > 0) {
    context += '=== FIN DU CYCLE PRÉCÉDENT ===\n';
    for (const m of previousCycleMessages) {
      context += `${m.role.toUpperCase()}: ${m.content}\n\n`;
    }
  }

  // Messages du cycle actuel
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

// ============================================
// SAUVEGARDE STATE - VERSION BATCH
// ============================================

async function saveGameState(partieId, state, previousCycle) {
  // Batch 1: Updates simples
  const batch1 = [
    supabase.from('parties').update({
      cycle_actuel: state.cycle,
      jour: state.jour,
      date_jeu: state.date_jeu,
      heure: state.heure
    }).eq('id', partieId)
  ];

  if (state.valentin) {
    // Retirer les champs qui ne sont pas dans la table
    const { partie_id, id, ...valentinData } = state.valentin;
    batch1.push(supabase.from('valentin').upsert({ 
      partie_id: partieId,
      ...valentinData
    }));
  }

  if (state.ia) {
    const { partie_id, id, ...iaData } = state.ia;
    batch1.push(supabase.from('ia_personnelle').upsert({ 
      partie_id: partieId,
      ...iaData
    }));
  }

  if (state.contexte) {
    const { partie_id, id, ...contexteData } = state.contexte;
    batch1.push(supabase.from('contexte').upsert({ 
      partie_id: partieId,
      ...contexteData
    }));
  }

  await Promise.all(batch1);

  // Batch 2: Arrays
  const batch2 = [];

  // PNJ
  if (state.pnj && state.pnj.length > 0) {
    const pnjToUpdate = state.pnj.filter(p => p.id);
    const pnjToInsert = state.pnj.filter(p => !p.id).map(p => {
      const { id, ...rest } = p;
      return { ...rest, partie_id: partieId };
    });
    
    for (const p of pnjToUpdate) {
      const { partie_id, ...pData } = p;
      batch2.push(supabase.from('pnj').update(pData).eq('id', p.id));
    }
    if (pnjToInsert.length > 0) {
      batch2.push(supabase.from('pnj').insert(pnjToInsert));
    }
  }

  // Arcs
  if (state.arcs && state.arcs.length > 0) {
    const arcsToUpdate = state.arcs.filter(a => a.id);
    const arcsToInsert = state.arcs.filter(a => !a.id).map(a => {
      const { id, ...rest } = a;
      return { ...rest, partie_id: partieId };
    });
    
    for (const a of arcsToUpdate) {
      const { partie_id, ...aData } = a;
      batch2.push(supabase.from('arcs').update(aData).eq('id', a.id));
    }
    if (arcsToInsert.length > 0) {
      batch2.push(supabase.from('arcs').insert(arcsToInsert));
    }
  }

  // Historique - insert du nouveau uniquement
  if (state.historique && state.historique.length > 0) {
    const newHistorique = state.historique.filter(h => !h.id).map(h => {
      const { id, ...rest } = h;
      return { ...rest, partie_id: partieId };
    });
    if (newHistorique.length > 0) {
      batch2.push(supabase.from('historique').insert(newHistorique));
    }
  }

  // Hors champ - insert du nouveau uniquement
  if (state.horsChamp && state.horsChamp.length > 0) {
    const newHorsChamp = state.horsChamp.filter(hc => !hc.id).map(hc => {
      const { id, ...rest } = hc;
      return { ...rest, partie_id: partieId };
    });
    if (newHorsChamp.length > 0) {
      batch2.push(supabase.from('hors_champ').insert(newHorsChamp));
    }
  }

  // Lieux - insert nouveaux uniquement
  if (state.lieux && state.lieux.length > 0) {
    const newLieux = state.lieux.filter(l => !l.id).map(l => {
      const { id, ...rest } = l;
      return { ...rest, partie_id: partieId };
    });
    if (newLieux.length > 0) {
      batch2.push(supabase.from('lieux').insert(newLieux));
    }
  }

  // A venir
  if (state.aVenir && state.aVenir.length > 0) {
    const aVenirToUpdate = state.aVenir.filter(av => av.id);
    const aVenirToInsert = state.aVenir.filter(av => !av.id).map(av => {
      const { id, ...rest } = av;
      return { ...rest, partie_id: partieId };
    });
    
    for (const av of aVenirToUpdate) {
      const { partie_id, ...avData } = av;
      batch2.push(supabase.from('a_venir').update(avData).eq('id', av.id));
    }
    if (aVenirToInsert.length > 0) {
      batch2.push(supabase.from('a_venir').insert(aVenirToInsert));
    }
  }

  if (batch2.length > 0) {
    await Promise.all(batch2);
  }

  // Générer résumé si changement de cycle
  if (state.cycle > previousCycle) {
    supabase
      .from('chat_messages')
      .select('role, content')
      .eq('partie_id', partieId)
      .eq('cycle', previousCycle)
      .order('created_at', { ascending: true })
      .then(({ data: cycleMessages }) => {
        if (cycleMessages && cycleMessages.length > 0) {
          generateCycleResume(partieId, previousCycle, cycleMessages, state).catch(console.error);
        }
      })
      .catch(console.error);
  }
}

// ============================================
// ROUTES - GET
// ============================================

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
    const { data } = await supabase
      .from('parties')
      .select('id, nom, cycle_actuel, updated_at, created_at')
      .eq('active', true)
      .order('updated_at', { ascending: false });
    return Response.json({ parties: data });
  }

  if (action === 'new') {
    try {
      const { data: partie, error: partieError } = await supabase
        .from('parties')
        .insert({ nom: 'Nouvelle partie', cycle_actuel: 1, active: true })
        .select()
        .single();
      
      if (partieError) throw partieError;

      await Promise.all([
        supabase.from('valentin').insert({ partie_id: partie.id }),
        supabase.from('ia_personnelle').insert({ partie_id: partie.id }),
        supabase.from('contexte').insert({ partie_id: partie.id })
      ]);

      return Response.json({ partieId: partie.id });
    } catch (e) {
      return Response.json({ error: e.message }, { status: 500 });
    }
  }

  if (action === 'delete' && partieId) {
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

// ============================================
// ROUTES - DELETE
// ============================================

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

// ============================================
// ROUTES - POST
// ============================================

export async function POST(request) {
  try {
    const { message, partieId, gameState } = await request.json();

    if (!partieId) {
      return Response.json({ error: 'partieId manquant' }, { status: 400 });
    }

    const currentCycle = gameState?.partie?.cycle_actuel || gameState?.cycle || 1;

    // Déterminer si c'est une init ou un tour normal
    const isInit = !gameState?.contexte?.station_nom || 
                   message.toLowerCase().includes('commencer') ||
                   message.toLowerCase().includes('nouvelle partie');

    // Créer le stream SSE
    const { readable, writable } = new TransformStream();
    const writer = writable.getWriter();
    const encoder = new TextEncoder();

    // Traitement en arrière-plan
    (async () => {
      let fullContent = '';
      let displayText = '';

      try {
        let systemPrompt, userContent;

        if (isInit) {
          systemPrompt = SYSTEM_PROMPT_INIT;
          userContent = 'Lance le jeu. Génère l\'univers, les personnages et l\'introduction.';
        } else {
          systemPrompt = SYSTEM_PROMPT_GAME;
          const conversationData = await loadConversationContext(partieId, currentCycle);
          userContent = buildConversationContext(conversationData, gameState, message);
        }

        // Appel Claude avec streaming
        const streamResponse = await anthropic.messages.stream({
          model: 'claude-sonnet-4-20250514',
          max_tokens: isInit ? 4096 : 2048, // Plus petit pour les tours normaux
          system: systemPrompt,
          messages: [{ role: 'user', content: userContent }]
        });

        // Streaming des chunks
        for await (const event of streamResponse) {
          if (event.type === 'content_block_delta' && event.delta?.text) {
            const chunk = event.delta.text;
            fullContent += chunk;
            await writer.write(encoder.encode(`data: ${JSON.stringify({ type: 'chunk', content: chunk })}\n\n`));
          }
        }

        // Parsing du JSON
        const parsed = tryFixJSON(fullContent);
        
        if (!parsed) {
          throw new Error('JSON non réparable');
        }

        // Construire le nouveau state
        let newState;
        
        if (parsed.type === 'init' && parsed.init) {
          // Génération initiale
          newState = buildInitialState(parsed.init, parsed.heure);
        } else {
          // Tour normal - appliquer le delta
          const { newState: updatedState, changelog } = applyDelta(gameState, parsed.delta || {});
          newState = updatedState;
          
          // Mettre à jour l'heure si fournie directement
          if (parsed.heure) {
            newState.heure = parsed.heure;
          }
          
          if (changelog.length > 0) {
            console.log('Delta appliqué:', changelog);
          }
        }

        // Construire le texte d'affichage
        displayText = '';
        if (parsed.heure) displayText += `[${parsed.heure}] `;
        if (parsed.narratif) displayText += parsed.narratif;
        if (parsed.choix && parsed.choix.length > 0) {
          displayText += '\n\n' + parsed.choix.map((c, i) => `${i + 1}. ${c}`).join('\n');
        }
        
        // Ajouter les arcs proposés pour l'init
        if (parsed.init?.arcs?.length > 0) {
          displayText += '\n\n**Arcs narratifs disponibles :**\n';
          displayText += parsed.init.arcs.map(a => 
            `- **${a.titre}** (${a.type}) : ${a.description}`
          ).join('\n');
        }

        // Envoyer le résultat final
        await writer.write(encoder.encode(`data: ${JSON.stringify({ 
          type: 'done', 
          displayText,
          state: newState,
          heure: parsed.heure
        })}\n\n`));

        // Sauvegarder les messages
        const cycleForSave = newState.cycle || currentCycle;
        
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

        // Sauvegarder le state
        await saveGameState(partieId, newState, currentCycle);

        await writer.write(encoder.encode(`data: ${JSON.stringify({ type: 'saved' })}\n\n`));

      } catch (error) {
        console.error('Streaming error:', error);
        
        // Essayer d'extraire quelque chose d'utile même en cas d'erreur
        if (fullContent) {
          const narratifMatch = fullContent.match(/"narratif"\s*:\s*"([^"]+)"/);
          if (narratifMatch) {
            displayText = narratifMatch[1].replace(/\\n/g, '\n');
          }
        }
        
        await writer.write(encoder.encode(`data: ${JSON.stringify({ 
          type: 'error', 
          error: error.message,
          partialContent: displayText || null
        })}\n\n`));
      } finally {
        try {
          await writer.close();
        } catch (e) {
          // Déjà fermé
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
