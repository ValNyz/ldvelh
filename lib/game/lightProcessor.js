/**
 * Traitement du mode LIGHT (messages normaux)
 * Version simplifiée - délègue l'extraction au nouvel orchestrateur
 */

import {
	getSceneEnCours,
	creerScene,
	fermerScene,
	ajouterPnjImpliques
} from '../scene/sceneService.js';
import { runExtractors } from '../kg/extractors/index.js';

// ============================================================================
// TRAITEMENT PRINCIPAL
// ============================================================================

/**
 * Traite une réponse light et met à jour l'état du jeu
 * Note: Les stats, transactions, relations sont maintenant gérées par les extracteurs
 */
export async function processLightMode(supabase, partieId, parsed, cycle, sceneEnCours) {
	const resultats = {
		scene_changed: false,
		nouveau_cycle: false,
		sceneId: sceneEnCours?.id || null
	};

	// 1. Changement de lieu = changement de scène
	const ancienLieu = sceneEnCours?.lieu;
	const nouveauLieu = parsed.lieu_actuel;

	if (isLieuChange(ancienLieu, nouveauLieu)) {
		const nouvelleScene = await gererChangementScene(
			supabase,
			partieId,
			cycle,
			ancienLieu,
			nouveauLieu,
			parsed.heure,
			parsed.pnjs_presents
		);
		resultats.scene_changed = true;
		resultats.sceneId = nouvelleScene?.id || null;
	}

	// 2. Mise à jour partie (heure, lieu, PNJ présents)
	await supabase.from('parties').update({
		heure: parsed.heure,
		lieu_actuel: parsed.lieu_actuel || ancienLieu,
		pnjs_presents: parsed.pnjs_presents || []
	}).eq('id', partieId);

	// 3. Ajouter PNJ à la scène
	if (parsed.pnjs_presents?.length > 0 && resultats.sceneId) {
		await ajouterPnjImpliques(supabase, resultats.sceneId, parsed.pnjs_presents);
	}

	// 4. Nouveau cycle (fin de journée)
	if (parsed.nouveau_cycle) {
		await handleNouveauCycle(
			supabase,
			partieId,
			cycle,
			parsed,
			resultats.sceneId
		);
		resultats.nouveau_cycle = true;
		resultats.sceneId = null;
	}

	return resultats;
}

// ============================================================================
// EXTRACTION BACKGROUND
// ============================================================================

/**
 * Lance l'extraction KG en background via les 5 extracteurs parallèles
 */
export async function extractionBackground(supabase, partieId, narratif, parsed, cycle, sceneId) {
	console.log('[BG] Lancement extraction parallèle...');

	// Récupérer les infos de la partie pour le contexte
	const { data: partie } = await supabase
		.from('parties')
		.select('jour, date_jeu, heure')
		.eq('id', partieId)
		.single();

	const result = await runExtractors(
		supabase,
		partieId,
		narratif,
		cycle,
		partie,
		parsed.pnjs_presents || [],
		sceneId
	);

	if (result.success) {
		console.log(`[BG] Extraction OK en ${result.metrics.duree_ms}ms`);
	} else {
		console.warn('[BG] Extraction avec erreurs:', result.metrics.erreurs);
	}

	return result;
}

// ============================================================================
// GESTION DES SCÈNES
// ============================================================================

function isLieuChange(ancien, nouveau) {
	if (!ancien || !nouveau) return false;
	return ancien.toLowerCase() !== nouveau.toLowerCase();
}

async function gererChangementScene(supabase, partieId, cycle, ancienLieu, nouveauLieu, heure, pnjsPresents) {
	const sceneEnCours = await getSceneEnCours(supabase, partieId);

	if (sceneEnCours) {
		console.log(`[SCENE] Changement: ${ancienLieu} → ${nouveauLieu}`);
		await fermerScene(supabase, sceneEnCours.id, heure, pnjsPresents);
	}

	const nouvelleScene = await creerScene(supabase, partieId, cycle, nouveauLieu, heure);
	return nouvelleScene;
}

async function handleNouveauCycle(supabase, partieId, cycle, parsed, sceneId) {
	await supabase.from('parties').update({
		cycle_actuel: cycle + 1,
		jour: parsed.nouveau_jour?.jour,
		date_jeu: parsed.nouveau_jour?.date_jeu
	}).eq('id', partieId);

	if (sceneId) {
		await fermerScene(supabase, sceneId, parsed.heure, parsed.pnjs_presents);
	}
}

// ============================================================================
// UTILITAIRES
// ============================================================================

export async function ensureSceneExists(supabase, partieId, cycle, lieu, heure) {
	let scene = await getSceneEnCours(supabase, partieId);

	if (!scene && lieu) {
		console.log(`[SCENE] Création première scène: ${lieu}`);
		scene = await creerScene(supabase, partieId, cycle, lieu, heure);
	}

	return scene;
}
