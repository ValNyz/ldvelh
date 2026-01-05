/**
 * Service de gestion des scènes pour LDVELH
 */

const SEUIL_ANALYSE_INTERMEDIAIRE = 30;

// ============================================================================
// RÉCUPÉRATION
// ============================================================================

/**
 * Récupère la scène en cours pour une partie
 */
export async function getSceneEnCours(supabase, partieId) {
	const { data, error } = await supabase
		.from('scenes')
		.select('*')
		.eq('partie_id', partieId)
		.eq('statut', 'en_cours')
		.order('created_at', { ascending: false })
		.limit(1)
		.maybeSingle();

	if (error) {
		console.error('[Scene] Erreur getSceneEnCours:', error);
		return null;
	}

	return data;
}

/**
 * Récupère les scènes analysées d'un cycle (pour le contexte)
 */
export async function getScenesAnalyseesCycle(supabase, partieId, cycle) {
	const { data, error } = await supabase
		.from('scenes')
		.select('numero, lieu, heure_debut, heure_fin, resume')
		.eq('partie_id', partieId)
		.eq('cycle', cycle)
		.eq('statut', 'analysee')
		.order('numero', { ascending: true });

	if (error) {
		console.error('[Scene] Erreur getScenesAnalyseesCycle:', error);
		return [];
	}

	return data || [];
}

/**
 * Récupère toutes les scènes d'un cycle (pour résumé de fin de cycle)
 */
export async function getScenesCompleteCycle(supabase, partieId, cycle) {
	const { data, error } = await supabase
		.from('scenes')
		.select('lieu, heure_debut, heure_fin, resume, resume_intermediaire')
		.eq('partie_id', partieId)
		.eq('cycle', cycle)
		.in('statut', ['terminee', 'analysee'])
		.order('numero', { ascending: true });

	if (error) {
		console.error('[Scene] Erreur getScenesCompleteCycle:', error);
		return [];
	}

	return data || [];
}

// ============================================================================
// CRÉATION / MODIFICATION
// ============================================================================

/**
 * Crée une nouvelle scène
 */
export async function creerScene(supabase, partieId, cycle, lieu, heure) {
	// Compter les scènes du cycle pour le numéro
	const { count, error: countError } = await supabase
		.from('scenes')
		.select('*', { count: 'exact', head: true })
		.eq('partie_id', partieId)
		.eq('cycle', cycle);

	if (countError) {
		console.error('[Scene] Erreur comptage:', countError);
	}

	const numero = (count || 0) + 1;

	const { data, error } = await supabase
		.from('scenes')
		.insert({
			partie_id: partieId,
			cycle,
			lieu,
			numero,
			heure_debut: heure,
			statut: 'en_cours',
			pnj_impliques: [],
			resume_intermediaire: []
		})
		.select()
		.single();

	if (error) {
		console.error('[Scene] Erreur création:', error);
		return null;
	}

	console.log(`[Scene] Créée: ${lieu} (cycle ${cycle}, #${numero})`);
	return data;
}

/**
 * Ferme une scène (changement de lieu)
 */
export async function fermerScene(supabase, sceneId, heureFin, pnjImpliques = []) {
	const { error } = await supabase
		.from('scenes')
		.update({
			statut: 'terminee',
			heure_fin: heureFin,
			pnj_impliques: pnjImpliques
		})
		.eq('id', sceneId);

	if (error) {
		console.error('[Scene] Erreur fermeture:', error);
		return false;
	}

	console.log(`[Scene] Fermée: ${sceneId}`);
	return true;
}

/**
 * Marque une scène comme analysée (après traitement Haiku)
 */
export async function marquerAnalysee(supabase, sceneId, resume) {
	const { error } = await supabase
		.from('scenes')
		.update({
			statut: 'analysee',
			resume
		})
		.eq('id', sceneId);

	if (error) {
		console.error('[Scene] Erreur marquage analysée:', error);
		return false;
	}

	return true;
}

/**
 * Ajoute un résumé intermédiaire (scène longue, tous les 30 messages)
 */
export async function ajouterResumeIntermediaire(supabase, sceneId, resumePartiel, dernierMessageId) {
	// Récupérer les résumés existants
	const { data: scene, error: fetchError } = await supabase
		.from('scenes')
		.select('resume_intermediaire')
		.eq('id', sceneId)
		.single();

	if (fetchError) {
		console.error('[Scene] Erreur fetch pour résumé intermédiaire:', fetchError);
		return false;
	}

	const resumesExistants = scene?.resume_intermediaire || [];
	const nouveauxResumes = [...resumesExistants, resumePartiel];

	const { error } = await supabase
		.from('scenes')
		.update({
			resume_intermediaire: nouveauxResumes,
			dernier_message_resume_id: dernierMessageId
		})
		.eq('id', sceneId);

	if (error) {
		console.error('[Scene] Erreur ajout résumé intermédiaire:', error);
		return false;
	}

	console.log(`[Scene] Résumé intermédiaire ajouté (${nouveauxResumes.length} total)`);
	return true;
}

// ============================================================================
// MESSAGES
// ============================================================================

/**
 * Récupère les messages d'une scène
 * @param depuisMessageId - Si fourni, récupère uniquement les messages après celui-ci
 */
export async function getMessagesScene(supabase, sceneId, depuisMessageId = null) {
	let query = supabase
		.from('chat_messages')
		.select('id, role, content, created_at')
		.eq('scene_id', sceneId)
		.order('created_at', { ascending: true });

	if (depuisMessageId) {
		// Récupérer le timestamp du message de référence
		const { data: refMsg, error: refError } = await supabase
			.from('chat_messages')
			.select('created_at')
			.eq('id', depuisMessageId)
			.single();

		if (refError || !refMsg) {
			console.error('[Scene] Erreur récup message référence:', refError);
		} else {
			query = query.gt('created_at', refMsg.created_at);
		}
	}

	const { data, error } = await query;

	if (error) {
		console.error('[Scene] Erreur getMessagesScene:', error);
		return [];
	}

	return data || [];
}

/**
 * Compte les messages d'une scène
 */
export async function compterMessagesScene(supabase, sceneId) {
	const { count, error } = await supabase
		.from('chat_messages')
		.select('*', { count: 'exact', head: true })
		.eq('scene_id', sceneId);

	if (error) {
		console.error('[Scene] Erreur comptage messages:', error);
		return 0;
	}

	return count || 0;
}

/**
 * Vérifie si une analyse intermédiaire est nécessaire (tous les 30 messages)
 */
export async function doitAnalyserIntermediaire(supabase, sceneId) {
	const count = await compterMessagesScene(supabase, sceneId);

	// Analyse quand on atteint un multiple de 30
	// et qu'on n'a pas déjà fait cette analyse
	if (count === 0 || count % SEUIL_ANALYSE_INTERMEDIAIRE !== 0) {
		return false;
	}

	// Vérifier combien de résumés intermédiaires on a déjà
	const { data: scene } = await supabase
		.from('scenes')
		.select('resume_intermediaire')
		.eq('id', sceneId)
		.single();

	const nbResumesExistants = scene?.resume_intermediaire?.length || 0;
	const nbResumesAttendus = Math.floor(count / SEUIL_ANALYSE_INTERMEDIAIRE);

	// On doit analyser si on n'a pas assez de résumés
	return nbResumesExistants < nbResumesAttendus;
}

/**
 * Récupère le dernier message d'une scène (pour référence)
 */
export async function getDernierMessageScene(supabase, sceneId) {
	const { data, error } = await supabase
		.from('chat_messages')
		.select('id, created_at')
		.eq('scene_id', sceneId)
		.order('created_at', { ascending: false })
		.limit(1)
		.maybeSingle();

	if (error) {
		console.error('[Scene] Erreur getDernierMessageScene:', error);
		return null;
	}

	return data;
}

// ============================================================================
// UTILITAIRES
// ============================================================================

/**
 * Met à jour les PNJ impliqués dans une scène
 */
export async function ajouterPnjImpliques(supabase, sceneId, nouveauxPnj) {
	if (!nouveauxPnj?.length) return;

	const { data: scene, error: fetchError } = await supabase
		.from('scenes')
		.select('pnj_impliques')
		.eq('id', sceneId)
		.single();

	if (fetchError) return;

	const existants = scene?.pnj_impliques || [];
	const tousLesPnj = [...new Set([...existants, ...nouveauxPnj])];

	await supabase
		.from('scenes')
		.update({ pnj_impliques: tousLesPnj })
		.eq('id', sceneId);
}

/**
 * Formate les résumés intermédiaires pour le contexte
 */
export function formaterResumesIntermediaires(resumeIntermediaire) {
	if (!resumeIntermediaire?.length) return null;

	return resumeIntermediaire.join(' ');
}

export { SEUIL_ANALYSE_INTERMEDIAIRE };
