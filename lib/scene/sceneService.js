/**
 * Service de gestion des scènes pour LDVELH
 */

import { SCENE_CONFIG } from '../constants.js';
import { dbOperation, dbOperationWithFallback } from '../errors.js';

// ============================================================================
// RÉCUPÉRATION
// ============================================================================

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

export async function getScenePrecedente(supabase, partieId, cycle, numero) {
	let query;

	if (numero > 1) {
		query = supabase
			.from('scenes')
			.select('*')
			.eq('partie_id', partieId)
			.eq('cycle', cycle)
			.eq('numero', numero - 1)
			.maybeSingle();
	} else {
		query = supabase
			.from('scenes')
			.select('*')
			.eq('partie_id', partieId)
			.eq('cycle', cycle - 1)
			.in('statut', ['terminee', 'analysee'])
			.order('numero', { ascending: false })
			.limit(1)
			.maybeSingle();
	}

	const { data, error } = await query;

	if (error) {
		console.error('[Scene] Erreur getScenePrecedente:', error);
		return null;
	}

	return data;
}

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

export async function creerScene(supabase, partieId, cycle, lieu, heure) {
	// Compter les scènes (avec fallback)
	const countResult = await dbOperationWithFallback(
		supabase
			.from('scenes')
			.select('*', { count: 'exact', head: true })
			.eq('partie_id', partieId)
			.eq('cycle', cycle),
		'compterScenesCycle',
		{ count: 0 }
	);

	const numero = (countResult?.count || 0) + 1;

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
		throw error;
	}

	console.log(`[Scene] Créée: ${lieu} (cycle ${cycle}, #${numero})`);
	return data;
}

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

export async function ajouterResumeIntermediaire(supabase, sceneId, resumePartiel, dernierMessageId) {
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

export async function getMessagesScene(supabase, sceneId, depuisMessageId = null) {
	let query = supabase
		.from('chat_messages')
		.select('id, role, content, created_at')
		.eq('scene_id', sceneId)
		.order('created_at', { ascending: true });

	if (depuisMessageId) {
		const { data: refMsg } = await supabase
			.from('chat_messages')
			.select('created_at')
			.eq('id', depuisMessageId)
			.single();

		if (refMsg) {
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

export async function doitAnalyserIntermediaire(supabase, sceneId) {
	const count = await compterMessagesScene(supabase, sceneId);

	if (count === 0 || count % SCENE_CONFIG.SEUIL_ANALYSE_INTERMEDIAIRE !== 0) {
		return false;
	}

	const { data: scene } = await supabase
		.from('scenes')
		.select('resume_intermediaire')
		.eq('id', sceneId)
		.single();

	const nbResumesExistants = scene?.resume_intermediaire?.length || 0;
	const nbResumesAttendus = Math.floor(count / SCENE_CONFIG.SEUIL_ANALYSE_INTERMEDIAIRE);

	return nbResumesExistants < nbResumesAttendus;
}

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

export async function ajouterPnjImpliques(supabase, sceneId, nouveauxPnj) {
	if (!nouveauxPnj?.length) return;

	const { data: scene } = await supabase
		.from('scenes')
		.select('pnj_impliques')
		.eq('id', sceneId)
		.single();

	if (!scene) return;

	const existants = scene.pnj_impliques || [];
	const tousLesPnj = [...new Set([...existants, ...nouveauxPnj])];

	await supabase
		.from('scenes')
		.update({ pnj_impliques: tousLesPnj })
		.eq('id', sceneId);
}

export function formaterResumesIntermediaires(resumeIntermediaire) {
	if (!resumeIntermediaire?.length) return null;
	return resumeIntermediaire.join(' ');
}
