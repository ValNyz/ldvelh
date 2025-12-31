/**
 * Context Builder pour LDVELH
 * 
 * Ce module construit un contexte intelligent pour Claude en exploitant
 * toutes les tables de la BDD pour maintenir la cohérence narrative.
 */

// ============================================================================
// EXTRACTION DES NOMS DE PNJ DEPUIS LE TEXTE
// ============================================================================

/**
 * Extrait les noms de PNJ potentiellement mentionnés dans les messages
 * Utilise des word boundaries pour éviter les faux positifs
 * @param {Array} messages - Messages récents [{role, content}]
 * @param {Array} knownPnj - Liste des PNJ connus [{nom, ...}]
 * @returns {Array} - Noms de PNJ trouvés
 */
function extractMentionedPnj(messages, knownPnj) {
  if (!messages || !knownPnj || knownPnj.length === 0) return [];
  
  const text = messages.map(m => m.content).join(' ').toLowerCase();
  const mentioned = [];
  
  // Fonction pour vérifier si un mot est isolé (word boundary)
  const isWordPresent = (textToSearch, word) => {
    const escaped = word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const regex = new RegExp(`(?:^|[\\s.,!?;:'"«»()\\-])${escaped}(?:[\\s.,!?;:'"«»()\\-]|$)`, 'i');
    return regex.test(textToSearch);
  };
  
  for (const pnj of knownPnj) {
    if (!pnj.nom) continue;
    
    const nomLower = pnj.nom.toLowerCase();
    const prenom = pnj.nom.split(' ')[0].toLowerCase();
    
    // Chercher le nom complet d'abord
    if (isWordPresent(text, nomLower)) {
      mentioned.push(pnj.nom);
      continue;
    }
    
    // Chercher le prénom seul (>= 3 caractères)
    if (prenom.length >= 3 && isWordPresent(text, prenom)) {
      mentioned.push(pnj.nom);
    }
  }
  
  return [...new Set(mentioned)]; // Dédupliquer
}

// ============================================================================
// FORMATAGE DES DONNÉES POUR LE CONTEXTE
// ============================================================================

/**
 * Formate une fiche PNJ pour le contexte Claude
 */
function formatPnjFiche(pnj, interactions = []) {
  let fiche = `## ${pnj.nom.toUpperCase()}`;
  fiche += ` (relation: ${pnj.relation ?? 0}/10, disposition: ${pnj.disposition || 'neutre'})`;
  fiche += `\n`;
  
  // Infos de base
  const infos = [];
  if (pnj.age) infos.push(`${pnj.age} ans`);
  if (pnj.metier) infos.push(pnj.metier);
  if (pnj.domicile) infos.push(`vit: ${pnj.domicile}`);
  if (infos.length > 0) fiche += `- ${infos.join(', ')}\n`;
  
  // Physique
  if (pnj.physique) fiche += `- Physique: ${pnj.physique}\n`;
  
  // Traits
  if (pnj.traits && pnj.traits.length > 0) {
    fiche += `- Traits: ${pnj.traits.join(', ')}\n`;
  }
  
  // Hobbies
  if (pnj.hobbies && pnj.hobbies.length > 0) {
    fiche += `- Hobbies: ${pnj.hobbies.join(', ')}\n`;
  }
  
  // Stats
  fiche += `- Stats: Social ${pnj.stat_social ?? 3}/5, Travail ${pnj.stat_travail ?? 3}/5, Santé ${pnj.stat_sante ?? 3}/5\n`;
  
  // Étape romantique (si > 0 ou si intérêt romantique)
  if (pnj.etape_romantique > 0 || pnj.interet_romantique) {
    const etapes = ['Inconnus', 'Indifférence', 'Reconnaissance', 'Sympathie', 'Curiosité', 'Intérêt', 'Attirance'];
    const etape = pnj.etape_romantique || 0;
    fiche += `- Étape romantique: ${etape}/6 (${etapes[etape] || '?'})\n`;
  }
  
  // Arc narratif
  if (pnj.arc) fiche += `- Arc: "${pnj.arc}"\n`;
  
  // Dernier contact
  if (pnj.dernier_contact) {
    fiche += `- Dernier contact: cycle ${pnj.dernier_contact}\n`;
  }
  
  // Cycles où le PNJ a été vu
  if (pnj.cycles_vus && pnj.cycles_vus.length > 0) {
    fiche += `- Vu aux cycles: ${pnj.cycles_vus.slice(-5).join(', ')}\n`;
  }
  
  // Détails importants
  if (pnj.details && pnj.details.length > 0) {
    fiche += `- Notes: ${pnj.details.slice(-3).join('; ')}\n`;
  }
  
  // Interactions récentes avec ce PNJ
  if (interactions.length > 0) {
    fiche += `- Interactions récentes:\n`;
    for (const inter of interactions.slice(0, 3)) {
      fiche += `  • [Cycle ${inter.cycle}${inter.heure ? ', ' + inter.heure : ''}]`;
      if (inter.lieu) fiche += ` @ ${inter.lieu}`;
      fiche += `: ${inter.resume || 'interaction'}`;
      if (inter.resultat) fiche += ` (${inter.resultat})`;
      fiche += `\n`;
    }
  }
  
  return fiche;
}

/**
 * Formate les arcs narratifs actifs
 */
function formatArcs(arcs) {
  if (!arcs || arcs.length === 0) return '';
  
  const arcsActifs = arcs.filter(a => a.etat === 'actif' || !a.etat);
  if (arcsActifs.length === 0) return '';
  
  let section = '=== ARCS NARRATIFS ACTIFS ===\n';
  
  for (const arc of arcsActifs) {
    section += `• ${arc.nom} (${arc.type || 'général'}) - ${arc.progression || 0}%\n`;
    if (arc.description) section += `  ${arc.description}\n`;
    if (arc.pnj_impliques && arc.pnj_impliques.length > 0) {
      section += `  PNJ: ${arc.pnj_impliques.join(', ')}\n`;
    }
  }
  
  return section + '\n';
}

/**
 * Formate l'historique récent
 */
function formatHistorique(historique) {
  if (!historique || historique.length === 0) return '';
  
  let section = '=== HISTORIQUE RÉCENT ===\n';
  
  for (const h of historique.slice(0, 3)) {
    section += `[Cycle ${h.cycle}${h.jour ? ', ' + h.jour : ''}]\n`;
    if (h.resume) section += `${h.resume}\n`;
    if (h.pnj_vus && h.pnj_vus.length > 0) {
      section += `PNJ rencontrés: ${h.pnj_vus.join(', ')}\n`;
    }
    if (h.decisions && h.decisions.length > 0) {
      section += `Décisions: ${h.decisions.join('; ')}\n`;
    }
    section += '\n';
  }
  
  return section;
}

/**
 * Formate les événements à venir
 */
function formatAVenir(aVenir) {
  if (!aVenir || aVenir.length === 0) return '';
  
  const nonRealises = aVenir.filter(e => !e.realise);
  if (nonRealises.length === 0) return '';
  
  let section = '=== ÉVÉNEMENTS PLANIFIÉS ===\n';
  
  for (const ev of nonRealises.slice(0, 5)) {
    section += `• [Cycle ${ev.cycle_prevu}] ${ev.evenement}`;
    if (ev.pnj_impliques && ev.pnj_impliques.length > 0) {
      section += ` (avec: ${ev.pnj_impliques.join(', ')})`;
    }
    section += '\n';
  }
  
  return section + '\n';
}

/**
 * Formate les événements hors-champ récents
 */
function formatHorsChamp(horsChamp) {
  if (!horsChamp || horsChamp.length === 0) return '';
  
  let section = '=== HORS-CHAMP (ce que Valentin ignore) ===\n';
  
  for (const hc of horsChamp.slice(0, 3)) {
    section += `• [Cycle ${hc.cycle}] ${hc.pnj_nom || 'PNJ'}: ${hc.evenement}\n`;
  }
  
  return section + '\n';
}

/**
 * Formate le contexte spatial (lieu actuel)
 */
function formatContexteSpatial(contexte, lieux = []) {
  if (!contexte) return '';
  
  let section = '=== CONTEXTE SPATIAL ===\n';
  section += `Station: ${contexte.station_nom || '?'} (${contexte.station_type || '?'})\n`;
  section += `Orbite: ${contexte.orbite || '?'} | Population: ${contexte.population || '?'}\n`;
  section += `Employeur: ${contexte.employeur_nom || '?'} (${contexte.employeur_type || '?'})\n`;
  if (contexte.ambiance) section += `Ambiance: ${contexte.ambiance}\n`;
  
  // Lieux connus
  if (lieux && lieux.length > 0) {
    section += `\nLieux découverts:\n`;
    for (const lieu of lieux.slice(0, 5)) {
      section += `• ${lieu.nom} (${lieu.type || 'lieu'})`;
      if (lieu.pnj_frequents && lieu.pnj_frequents.length > 0) {
        section += ` - fréquenté par: ${lieu.pnj_frequents.join(', ')}`;
      }
      section += '\n';
    }
  }
  
  return section + '\n';
}

/**
 * Formate l'état de Valentin
 * Gère les deux formats possibles : 
 * - Format Claude: valentin.competences.informatique
 * - Format Supabase: valentin.comp_informatique
 */
function formatValentin(valentin, ia) {
  if (!valentin) return '';
  
  let section = '=== ÉTAT DE VALENTIN ===\n';
  section += `Énergie: ${valentin.energie ?? 3}/5 | Moral: ${valentin.moral ?? 3}/5 | Santé: ${valentin.sante ?? 5}/5\n`;
  section += `Crédits: ${valentin.credits ?? 1400}\n`;
  
  // Compétences - gère les deux formats
  const comps = valentin.competences || {};
  const getComp = (name, fallback) => comps[name] ?? valentin[`comp_${name}`] ?? fallback;
  
  section += `Compétences: Info ${getComp('informatique', 5)}/5, Systèmes ${getComp('systemes', 4)}/5, `;
  section += `Social ${getComp('social', 2)}/5, Cuisine ${getComp('cuisine', 3)}/5, `;
  section += `Bricolage ${getComp('bricolage', 3)}/5, Médical ${getComp('medical', 1)}/5\n`;
  
  // Traits et hobbies
  if (valentin.traits && valentin.traits.length > 0) {
    section += `Traits: ${valentin.traits.join(', ')}\n`;
  }
  if (valentin.hobbies && valentin.hobbies.length > 0) {
    section += `Hobbies: ${valentin.hobbies.join(', ')}\n`;
  }
  
  // Poste et raison du départ
  if (valentin.poste) {
    section += `Poste: ${valentin.poste}\n`;
  }
  if (valentin.raison_depart) {
    section += `Raison du départ: ${valentin.raison_depart}\n`;
  }
  
  // Logement
  if (valentin.logement_adresse) {
    section += `Logement: ${valentin.logement_adresse} (état: ${valentin.logement ?? 0}%)\n`;
  }
  
  // Inventaire
  if (valentin.inventaire && valentin.inventaire.length > 0) {
    section += `Inventaire: ${valentin.inventaire.join(', ')}\n`;
  }
  
  // IA personnelle
  if (ia && ia.nom) {
    section += `IA: ${ia.nom} (${ia.traits ? ia.traits.join(', ') : 'sarcastique'})\n`;
  }
  
  return section + '\n';
}

// ============================================================================
// CONSTRUCTION DU CONTEXTE COMPLET
// ============================================================================

/**
 * Construit le contexte complet pour Claude
 * 
 * @param {Object} params
 * @param {Object} params.gameState - État du jeu actuel
 * @param {Array} params.allPnj - Tous les PNJ de la partie
 * @param {Array} params.interactions - Interactions récentes
 * @param {Array} params.recentMessages - Messages récents du chat
 * @param {Array} params.cycleResumes - Résumés des cycles passés
 * @param {string} params.userMessage - Message actuel du joueur
 * @returns {string} - Contexte formaté pour Claude
 */
function buildContext({
  gameState,
  allPnj = [],
  interactions = [],
  recentMessages = [],
  cycleResumes = [],
  userMessage
}) {
  let context = '';
  
  // 1. Résumés des cycles anciens (mémoire long-terme)
  if (cycleResumes.length > 0) {
    context += '=== RÉSUMÉS CYCLES PRÉCÉDENTS ===\n';
    for (const r of cycleResumes) {
      context += `[Cycle ${r.cycle}${r.jour ? ', ' + r.jour : ''}] ${r.resume}\n`;
      if (r.evenements_cles && r.evenements_cles.length > 0) {
        const cles = Array.isArray(r.evenements_cles) ? r.evenements_cles : [];
        if (cles.length > 0) {
          context += `  Événements clés: ${cles.join('; ')}\n`;
        }
      }
    }
    context += '\n';
  }
  
  // 2. État de Valentin
  context += formatValentin(gameState?.valentin, gameState?.ia);
  
  // 3. Contexte spatial
  context += formatContexteSpatial(gameState?.contexte, gameState?.lieux);
  
  // 4. PNJ - Focus sur ceux mentionnés récemment + tous si peu nombreux
  const mentionedPnjNames = extractMentionedPnj(recentMessages, allPnj);
  const currentCycle = gameState?.partie?.cycle_actuel || 1;
  
  const pnjToInclude = allPnj.length <= 5 
    ? allPnj 
    : allPnj.filter(p => 
        mentionedPnjNames.includes(p.nom) || 
        p.est_initial || 
        p.interet_romantique ||
        (p.dernier_contact && p.dernier_contact >= currentCycle - 2)
      );
  
  if (pnjToInclude.length > 0) {
    context += '=== PERSONNAGES ===\n';
    for (const pnj of pnjToInclude) {
      const pnjInteractions = interactions.filter(i => 
        i.pnj_id === pnj.id || 
        (i.pnj_nom && pnj.nom && i.pnj_nom.toLowerCase() === pnj.nom.toLowerCase())
      );
      context += formatPnjFiche(pnj, pnjInteractions);
      context += '\n';
    }
  }
  
  // 5. Arcs narratifs actifs
  if (gameState?.arcs) {
    context += formatArcs(gameState.arcs);
  }
  
  // 6. Historique récent
  if (gameState?.historique) {
    context += formatHistorique(gameState.historique);
  }
  
  // 7. Événements à venir
  if (gameState?.aVenir) {
    context += formatAVenir(gameState.aVenir);
  }
  
  // 8. Hors-champ (pour le MJ)
  if (gameState?.horsChamp) {
    context += formatHorsChamp(gameState.horsChamp);
  }
  
  // 9. Messages récents du cycle actuel (conversation directe)
  if (recentMessages.length > 0) {
    context += '=== CONVERSATION RÉCENTE ===\n';
    for (const m of recentMessages.slice(-6)) {
      const role = m.role === 'user' ? 'VALENTIN' : 'MJ';
      // Tronquer les messages trop longs
      const content = m.content.length > 500 ? m.content.slice(0, 500) + '...' : m.content;
      context += `${role}: ${content}\n\n`;
    }
  }
  
  // 10. Action actuelle du joueur
  context += '=== ACTION DU JOUEUR ===\n';
  context += userMessage;
  
  return context;
}

// ============================================================================
// FONCTION PRINCIPALE D'EXPORT
// ============================================================================

/**
 * Charge les données nécessaires et construit le contexte
 * À appeler depuis route.js
 * 
 * @param {Object} supabase - Client Supabase
 * @param {string} partieId - ID de la partie
 * @param {Object} gameState - État du jeu (depuis le client)
 * @param {string} userMessage - Message du joueur
 * @param {Array} [preloadedPnj] - PNJ déjà chargés (optionnel, évite double requête)
 * @returns {Promise<{context: string, pnj: Array}>} - Contexte formaté et PNJ chargés
 */
async function buildContextForClaude(supabase, partieId, gameState, userMessage, preloadedPnj = null) {
  const currentCycle = gameState?.partie?.cycle_actuel || 1;
  
  // Construire les requêtes en parallèle
  const queries = [];
  
  // Requête PNJ seulement si pas préchargés
  if (!preloadedPnj) {
    queries.push(
      supabase.from('pnj')
        .select('*')
        .eq('partie_id', partieId)
        .order('dernier_contact', { ascending: false, nullsFirst: false })
    );
  }
  
  // Interactions des 3 derniers cycles
  queries.push(
    supabase.from('interactions')
      .select('*')
      .eq('partie_id', partieId)
      .gte('cycle', Math.max(1, currentCycle - 2))
      .order('cycle', { ascending: false })
      .order('created_at', { ascending: false })
      .limit(15)
  );
  
  // Messages du cycle actuel + fin du précédent
  queries.push(
    supabase.from('chat_messages')
      .select('role, content, cycle, created_at')
      .eq('partie_id', partieId)
      .gte('cycle', Math.max(1, currentCycle - 1))
      .order('created_at', { ascending: true })
  );
  
  // Résumés des cycles anciens
  queries.push(
    supabase.from('cycle_resumes')
      .select('cycle, jour, date_jeu, resume, evenements_cles')
      .eq('partie_id', partieId)
      .lt('cycle', currentCycle)
      .order('cycle', { ascending: false })
      .limit(3)
  );
  
  const results = await Promise.all(queries);
  
  // Extraire les résultats selon si PNJ préchargés ou non
  let pnjData, interactionsData, messagesData, resumesData;
  
  if (preloadedPnj) {
    pnjData = preloadedPnj;
    [interactionsData, messagesData, resumesData] = results.map(r => r.data || []);
  } else {
    const [pnjResult, interactionsResult, messagesResult, resumesResult] = results;
    pnjData = pnjResult.data || [];
    interactionsData = interactionsResult.data || [];
    messagesData = messagesResult.data || [];
    resumesData = resumesResult.data || [];
  }
  
  // Filtrer les messages pour le cycle actuel et les derniers du précédent
  const currentCycleMessages = messagesData.filter(m => m.cycle === currentCycle);
  const previousCycleMessages = messagesData
    .filter(m => m.cycle === currentCycle - 1)
    .slice(-4); // 4 derniers du cycle précédent
  
  const recentMessages = [...previousCycleMessages, ...currentCycleMessages];
  
  const context = buildContext({
    gameState,
    allPnj: pnjData,
    interactions: interactionsData,
    recentMessages,
    cycleResumes: resumesData.reverse(), // Plus ancien en premier
    userMessage
  });
  
  // Retourner le contexte ET les PNJ pour réutilisation
  return {
    context,
    pnj: pnjData
  };
}

// ============================================================================
// EXPORTS
// ============================================================================

export {
  buildContext,
  buildContextForClaude,
  extractMentionedPnj,
  formatPnjFiche,
  formatArcs,
  formatHistorique,
  formatAVenir,
  formatHorsChamp,
  formatContexteSpatial,
  formatValentin
};
