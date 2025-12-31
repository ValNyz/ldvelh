/**
 * Interaction Tracker pour LDVELH
 * 
 * Ce module gère :
 * - La sauvegarde des interactions PNJ générées par Claude
 * - La mise à jour automatique des PNJ (dernier_contact, cycles_vus)
 * - L'extraction des PNJ mentionnés dans le narratif
 */

// ============================================================================
// EXTRACTION DES PNJ DEPUIS LE NARRATIF
// ============================================================================

/**
 * Extrait les noms de PNJ mentionnés dans le texte narratif
 * Utilise des word boundaries pour éviter les faux positifs
 * @param {string} narratif - Texte narratif de Claude
 * @param {Array} knownPnj - Liste des PNJ connus [{nom, ...}]
 * @returns {Array} - PNJ trouvés (objets complets, pas juste les noms)
 */
function extractPnjFromNarratif(narratif, knownPnj) {
  if (!narratif || !knownPnj || knownPnj.length === 0) return [];
  
  const textLower = narratif.toLowerCase();
  const mentioned = [];
  
  // Fonction pour vérifier si un mot est isolé (word boundary)
  const isWordPresent = (text, word) => {
    // Escape les caractères spéciaux regex
    const escaped = word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    // Word boundary : début/fin de string, espace, ponctuation
    const regex = new RegExp(`(?:^|[\\s.,!?;:'"«»()\\-])${escaped}(?:[\\s.,!?;:'"«»()\\-]|$)`, 'i');
    return regex.test(text);
  };
  
  for (const pnj of knownPnj) {
    if (!pnj.nom) continue;
    
    const nomLower = pnj.nom.toLowerCase();
    const prenom = pnj.nom.split(' ')[0].toLowerCase();
    
    // Chercher le nom complet d'abord (plus fiable)
    if (isWordPresent(textLower, nomLower)) {
      mentioned.push(pnj);
      continue;
    }
    
    // Chercher le prénom seul (seulement si >= 3 caractères pour éviter "Max" dans "maximum")
    if (prenom.length >= 3 && isWordPresent(textLower, prenom)) {
      mentioned.push(pnj);
    }
  }
  
  return mentioned;
}

// ============================================================================
// SAUVEGARDE DES INTERACTIONS
// ============================================================================

/**
 * Sauvegarde les interactions générées par Claude
 * @param {Object} supabase - Client Supabase
 * @param {string} partieId - ID de la partie
 * @param {number} cycle - Cycle actuel
 * @param {string} heure - Heure in-game
 * @param {Array} interactions - Interactions générées par Claude
 * @param {Array} knownPnj - Liste des PNJ connus pour récupérer les IDs
 * @returns {Promise<{saved: number, errors: Array}>}
 */
async function saveInteractions(supabase, partieId, cycle, heure, interactions, knownPnj) {
  if (!interactions || interactions.length === 0) {
    return { saved: 0, errors: [] };
  }
  
  const errors = [];
  const toInsert = [];
  
  for (const inter of interactions) {
    if (!inter.pnj_nom) {
      errors.push('Interaction sans pnj_nom ignorée');
      continue;
    }
    
    // Trouver le PNJ correspondant (insensible à la casse)
    const pnj = knownPnj.find(p => 
      p.nom && (
        p.nom.toLowerCase() === inter.pnj_nom.toLowerCase() ||
        p.nom.split(' ')[0].toLowerCase() === inter.pnj_nom.toLowerCase()
      )
    );
    
    toInsert.push({
      partie_id: partieId,
      pnj_id: pnj?.id || null,
      cycle: cycle,
      heure: heure || inter.heure || null,
      lieu: inter.lieu || null,
      resume: inter.resume || 'Interaction',
      resultat: inter.resultat || 'neutre',
      changement_relation: parseFloat(inter.changement_relation) || 0,
      details: inter.details || null
    });
  }
  
  if (toInsert.length > 0) {
    const { error } = await supabase.from('interactions').insert(toInsert);
    if (error) {
      errors.push(`Erreur insert interactions: ${error.message}`);
      return { saved: 0, errors };
    }
  }
  
  return { saved: toInsert.length, errors };
}

// ============================================================================
// MISE À JOUR DES PNJ
// ============================================================================

/**
 * Met à jour dernier_contact et cycles_vus pour les PNJ mentionnés
 * @param {Object} supabase - Client Supabase
 * @param {string} partieId - ID de la partie
 * @param {number} cycle - Cycle actuel
 * @param {Array} pnjMentionnes - PNJ mentionnés (objets avec id)
 * @returns {Promise<{updated: number, errors: Array}>}
 */
async function updatePnjContact(supabase, partieId, cycle, pnjMentionnes) {
  if (!pnjMentionnes || pnjMentionnes.length === 0) {
    return { updated: 0, errors: [] };
  }
  
  const errors = [];
  let updated = 0;
  
  // Préparer les updates en batch pour optimiser
  const updates = [];
  
  for (const pnj of pnjMentionnes) {
    if (!pnj.id) continue;
    
    // Récupérer cycles_vus actuel et ajouter le cycle si pas déjà présent
    const cyclesVus = Array.isArray(pnj.cycles_vus) ? [...pnj.cycles_vus] : [];
    if (!cyclesVus.includes(cycle)) {
      cyclesVus.push(cycle);
    }
    
    updates.push({
      id: pnj.id,
      dernier_contact: cycle,
      cycles_vus: cyclesVus,
      updated_at: new Date().toISOString()
    });
  }
  
  // Exécuter les updates (Supabase ne supporte pas le bulk update, donc séquentiel)
  for (const update of updates) {
    const { id, ...data } = update;
    const { error } = await supabase
      .from('pnj')
      .update(data)
      .eq('id', id);
    
    if (error) {
      errors.push(`Erreur update PNJ ${id}: ${error.message}`);
    } else {
      updated++;
    }
  }
  
  return { updated, errors };
}

/**
 * Met à jour la relation d'un PNJ basé sur les interactions
 * @param {Object} supabase - Client Supabase
 * @param {Array} interactions - Interactions avec changement_relation
 * @param {Array} knownPnj - Liste des PNJ connus
 * @returns {Promise<{updated: number, errors: Array}>}
 */
async function updatePnjRelations(supabase, interactions, knownPnj) {
  if (!interactions || interactions.length === 0) {
    return { updated: 0, errors: [] };
  }
  
  const errors = [];
  let updated = 0;
  
  // Grouper les changements par PNJ
  const changementsByPnj = {};
  
  for (const inter of interactions) {
    if (!inter.pnj_nom || !inter.changement_relation) continue;
    
    const pnj = knownPnj.find(p => 
      p.nom && (
        p.nom.toLowerCase() === inter.pnj_nom.toLowerCase() ||
        p.nom.split(' ')[0].toLowerCase() === inter.pnj_nom.toLowerCase()
      )
    );
    
    if (pnj?.id) {
      if (!changementsByPnj[pnj.id]) {
        changementsByPnj[pnj.id] = { pnj, total: 0 };
      }
      changementsByPnj[pnj.id].total += parseFloat(inter.changement_relation) || 0;
    }
  }
  
  // Appliquer les changements
  for (const [pnjId, data] of Object.entries(changementsByPnj)) {
    const newRelation = Math.max(0, Math.min(10, (data.pnj.relation || 0) + data.total));
    
    const { error } = await supabase
      .from('pnj')
      .update({ 
        relation: newRelation,
        updated_at: new Date().toISOString()
      })
      .eq('id', pnjId);
    
    if (error) {
      errors.push(`Erreur update relation PNJ ${pnjId}: ${error.message}`);
    } else {
      updated++;
    }
  }
  
  return { updated, errors };
}

// ============================================================================
// FONCTION PRINCIPALE
// ============================================================================

/**
 * Traite les interactions après une réponse de Claude
 * 
 * @param {Object} supabase - Client Supabase
 * @param {string} partieId - ID de la partie
 * @param {number} cycle - Cycle actuel
 * @param {string} heure - Heure in-game
 * @param {string} narratif - Texte narratif de Claude
 * @param {Array} interactionsFromClaude - Interactions explicites générées par Claude
 * @param {Array} knownPnj - Liste des PNJ connus
 * @returns {Promise<Object>} - Résultats du traitement
 */
async function processInteractions(supabase, partieId, cycle, heure, narratif, interactionsFromClaude, knownPnj) {
  const results = {
    pnjMentionnes: [],
    interactionsSaved: 0,
    pnjUpdated: 0,
    relationsUpdated: 0,
    errors: []
  };
  
  if (!partieId || !knownPnj) {
    results.errors.push('partieId ou knownPnj manquant');
    return results;
  }
  
  // 1. Extraire les PNJ mentionnés dans le narratif
  const pnjFromNarratif = extractPnjFromNarratif(narratif, knownPnj);
  
  // 2. Extraire les PNJ des interactions explicites
  const pnjFromInteractions = (interactionsFromClaude || [])
    .map(inter => knownPnj.find(p => 
      p.nom && inter.pnj_nom && (
        p.nom.toLowerCase() === inter.pnj_nom.toLowerCase() ||
        p.nom.split(' ')[0].toLowerCase() === inter.pnj_nom.toLowerCase()
      )
    ))
    .filter(Boolean);
  
  // 3. Fusionner et dédupliquer les PNJ mentionnés
  const allMentionedMap = new Map();
  for (const pnj of [...pnjFromNarratif, ...pnjFromInteractions]) {
    if (pnj.id && !allMentionedMap.has(pnj.id)) {
      allMentionedMap.set(pnj.id, pnj);
    }
  }
  const allMentioned = Array.from(allMentionedMap.values());
  results.pnjMentionnes = allMentioned.map(p => p.nom);
  
  // 4. Sauvegarder les interactions explicites
  if (interactionsFromClaude && interactionsFromClaude.length > 0) {
    const saveResult = await saveInteractions(
      supabase, partieId, cycle, heure, interactionsFromClaude, knownPnj
    );
    results.interactionsSaved = saveResult.saved;
    results.errors.push(...saveResult.errors);
    
    // 4b. Mettre à jour les relations basées sur les interactions
    const relResult = await updatePnjRelations(supabase, interactionsFromClaude, knownPnj);
    results.relationsUpdated = relResult.updated;
    results.errors.push(...relResult.errors);
  }
  
  // 5. Mettre à jour dernier_contact et cycles_vus pour tous les PNJ mentionnés
  if (allMentioned.length > 0) {
    const updateResult = await updatePnjContact(supabase, partieId, cycle, allMentioned);
    results.pnjUpdated = updateResult.updated;
    results.errors.push(...updateResult.errors);
  }
  
  return results;
}

// ============================================================================
// GÉNÉRATION D'INTERACTIONS AUTOMATIQUES (FALLBACK)
// ============================================================================

/**
 * Génère des interactions basiques si Claude n'en a pas fourni
 * Utilisé comme fallback pour maintenir la cohérence
 * 
 * @param {string} narratif - Texte narratif
 * @param {Array} pnjMentionnes - PNJ détectés dans le narratif (objets complets)
 * @param {string} heure - Heure in-game
 * @returns {Array} - Interactions générées
 */
function generateFallbackInteractions(narratif, pnjMentionnes, heure) {
  if (!pnjMentionnes || pnjMentionnes.length === 0) return [];
  if (!narratif) return [];
  
  // Analyse basique du ton du narratif
  const narratifLower = narratif.toLowerCase();
  let resultat = 'neutre';
  let changement = 0;
  
  const positiveWords = ['sourit', 'sourire', 'rit', 'rire', 'merci', 'content', 'heureux', 
    'amical', 'chaleureux', 'aide', 'gentil', 'apprécié', 'sympathique', 'agréable'];
  const negativeWords = ['froid', 'distant', 'agacé', 'irrité', 'refuse', 'ignore', 
    'méfiant', 'hostile', 'ennuyé', 'impatient', 'sec', 'brusque'];
  
  const hasPositive = positiveWords.some(w => narratifLower.includes(w));
  const hasNegative = negativeWords.some(w => narratifLower.includes(w));
  
  if (hasPositive && !hasNegative) {
    resultat = 'positif';
    changement = 0.25; // Changement modeste pour le fallback
  } else if (hasNegative && !hasPositive) {
    resultat = 'negatif';
    changement = -0.25;
  }
  
  // Générer une interaction par PNJ mentionné
  return pnjMentionnes.map(pnj => ({
    pnj_nom: pnj.nom,
    heure: heure || null,
    lieu: null, // Pas d'info de lieu en fallback
    resume: `Échange avec ${pnj.nom}`,
    resultat: resultat,
    changement_relation: changement
  }));
}

// ============================================================================
// EXPORTS
// ============================================================================

export {
  extractPnjFromNarratif,
  saveInteractions,
  updatePnjContact,
  updatePnjRelations,
  processInteractions,
  generateFallbackInteractions
};
