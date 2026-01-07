/**
 * Traitement du mode LIGHT (messages normaux)
 */

import { runExtractors } from '../kg/extractors/index.js';

// ============================================================================
// TRAITEMENT PRINCIPAL
// ============================================================================

/**
 * Traite une réponse light et met à jour l'état du jeu
 * Note: Les stats, transactions, relations sont maintenant gérées par les extracteurs
 */

export async function processLightMode(supabase, partieId, parsed, cycle) {
	const resultats = {
		nouveau_cycle: false
	};

	// 1. Mise à jour partie (heure, lieu, PNJ présents)
	await supabase.from('parties').update({
		heure: parsed.heure,
		lieu_actuel: parsed.lieu_actuel,
		pnjs_presents: parsed.pnjs_presents || []
	}).eq('id', partieId);

	// 2. Nouveau cycle (fin de journée)
	if (parsed.nouveau_cycle) {
		await handleNouveauCycle(supabase, partieId, cycle, parsed);
		resultats.nouveau_cycle = true;
	}

	return resultats;
}

// ============================================================================
// EXTRACTION BACKGROUND
// ============================================================================

/**
 * Lance l'extraction KG en background via les 5 extracteurs parallèles
 */
export async function extractionBackground(supabase, partieId, narratif, parsed, cycle) {
	console.log('[BG] Lancement extraction parallèle...');

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
		parsed.pnjs_presents || []
	);

	if (result.success) {
		console.log(`[BG] Extraction OK en ${result.metrics.duree_ms}ms`);
	} else {
		console.warn('[BG] Extraction avec erreurs:', result.metrics.erreurs);
	}

	return result;
}

// ============================================================================
// GESTION DU NOUVEAU CYCLE
// ============================================================================

async function handleNouveauCycle(supabase, partieId, cycle, parsed) {
	await supabase.from('parties').update({
		cycle_actuel: cycle + 1,
		jour: parsed.nouveau_jour?.jour,
		date_jeu: parsed.nouveau_jour?.date_jeu
	}).eq('id', partieId);
}
