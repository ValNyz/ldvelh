/**
 * Traitement du mode LIGHT (messages normaux)
 */

import {
	updateStatsValentin,
	creerTransaction
} from '../kg/kgService.js';
import {
	getSceneEnCours,
	creerScene,
	fermerScene,
	ajouterPnjImpliques
} from '../scene/sceneService.js';
import { extraireEtAppliquer, doitExtraire } from '../kg/kgExtractor.js';

// ============================================================================
// TRAITEMENT PRINCIPAL
// ============================================================================

/**
 * Traite une réponse light et met à jour le Knowledge Graph
 * @param {object} supabase - Client Supabase
 * @param {string} partieId - ID de la partie
 * @param {object} parsed - Réponse Claude parsée
 * @param {number} cycle - Cycle actuel
 * @param {object} sceneEnCours - Scène en cours (peut être null)
 * @returns {Promise<object>} Résultats du traitement
 */
export async function processLightMode(supabase, partieId, parsed, cycle, sceneEnCours) {
	const resultats = {
		stats_updated: false,
		transactions: 0,
		scene_changed: false,
		nouveau_cycle: false,
		sceneId: sceneEnCours?.id || null
	};

	// 1. Deltas Valentin (stats)
	if (hasStatChanges(parsed.deltas_valentin)) {
		await updateStatsValentin(supabase, partieId, cycle, parsed.deltas_valentin);
		resultats.stats_updated = true;
	}

	// 2. Transactions
	if (parsed.transactions?.length > 0) {
		await processTransactions(supabase, partieId, cycle, parsed);
		resultats.transactions = parsed.transactions.length;
	}

	// 3. Changement de lieu = changement de scène
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

	// 4. Mise à jour partie
	await supabase.from('parties').update({
		heure: parsed.heure,
		lieu_actuel: parsed.lieu_actuel || ancienLieu,
		pnjs_presents: parsed.pnjs_presents || []
	}).eq('id', partieId);

	// 5. Ajouter PNJ à la scène
	if (parsed.pnjs_presents?.length > 0 && resultats.sceneId) {
		await ajouterPnjImpliques(supabase, resultats.sceneId, parsed.pnjs_presents);
	}

	// 6. Nouveau cycle
	if (parsed.nouveau_cycle) {
		await handleNouveauCycle(
			supabase,
			partieId,
			cycle,
			parsed,
			resultats.sceneId
		);
		resultats.nouveau_cycle = true;
		resultats.sceneId = null; // La scène a été fermée
	}

	return resultats;
}

// ============================================================================
// HELPERS
// ============================================================================

function hasStatChanges(deltas) {
	if (!deltas) return false;
	return deltas.energie || deltas.moral || deltas.sante;
}

function isLieuChange(ancien, nouveau) {
	if (!ancien || !nouveau) return false;
	return ancien.toLowerCase() !== nouveau.toLowerCase();
}

async function processTransactions(supabase, partieId, cycle, parsed) {
	const resultats = { reussies: 0, echouees: 0, doublons: 0 };

	for (const tx of parsed.transactions) {
		const result = await creerTransaction(supabase, partieId, cycle, {
			type: tx.type,
			montant: tx.montant,
			description: tx.description,
			objet: tx.objet,
			quantite: tx.quantite,
			heure: parsed.heure
		});

		if (result.success) {
			resultats.reussies++;
		} else if (result.doublon) {
			resultats.doublons++;
		} else {
			resultats.echouees++;
			console.warn(`[TX] Échec: ${tx.description} - ${result.error}`);
		}
	}

	return resultats;
}

// ============================================================================
// GESTION DES SCÈNES
// ============================================================================

/**
 * Gère un changement de scène (changement de lieu)
 */
async function gererChangementScene(supabase, partieId, cycle, ancienLieu, nouveauLieu, heure, pnjsPresents) {
	const sceneEnCours = await getSceneEnCours(supabase, partieId);

	if (sceneEnCours) {
		console.log(`[SCENE] Changement: ${ancienLieu} → ${nouveauLieu}`);

		// Fermer l'ancienne scène
		await fermerScene(supabase, sceneEnCours.id, heure, pnjsPresents);

		// Extraction KG en background
		extraireSceneEnBackground(supabase, partieId, sceneEnCours.id, cycle);
	}

	// Créer la nouvelle scène
	const nouvelleScene = await creerScene(supabase, partieId, cycle, nouveauLieu, heure);
	return nouvelleScene;
}

/**
 * Gère le passage à un nouveau cycle (fin de journée)
 */
async function handleNouveauCycle(supabase, partieId, cycle, parsed, sceneId) {
	// Mettre à jour la partie
	await supabase.from('parties').update({
		cycle_actuel: cycle + 1,
		jour: parsed.nouveau_jour?.jour,
		date_jeu: parsed.nouveau_jour?.date_jeu
	}).eq('id', partieId);

	// Fermer la scène en cours
	if (sceneId) {
		await fermerScene(supabase, sceneId, parsed.heure, parsed.pnjs_presents);
		extraireSceneEnBackground(supabase, partieId, sceneId, cycle);
	}
}

// ============================================================================
// EXTRACTION BACKGROUND
// ============================================================================

/**
 * Lance l'extraction KG en background (non-bloquant)
 */
function extraireSceneEnBackground(supabase, partieId, sceneId, cycle) {
	// Fire and forget
	(async () => {
		try {
			const { data: messages } = await supabase
				.from('chat_messages')
				.select('role, content')
				.eq('scene_id', sceneId)
				.order('created_at');

			if (!messages?.length) return;

			const narratif = messages
				.filter(m => m.role === 'assistant')
				.map(m => m.content)
				.join('\n\n');

			if (narratif.trim()) {
				const result = await extraireEtAppliquer(supabase, partieId, narratif, cycle, sceneId);

				if (result.success && result.resume) {
					await supabase
						.from('scenes')
						.update({ statut: 'analysee', resume: result.resume })
						.eq('id', sceneId);
				}
			}
		} catch (err) {
			console.error('[SCENE] Erreur extraction background:', err);
		}
	})();
}

/**
 * Extraction KG conditionnelle après un message
 */
export async function extractionBackground(supabase, partieId, narratif, parsed, cycle, sceneId) {
	// Vérifier si extraction nécessaire
	if (!doitExtraire(narratif, parsed)) {
		console.log('[KG] Extraction non nécessaire');
		return null;
	}

	console.log('[KG] Lancement extraction background...');

	try {
		const result = await extraireEtAppliquer(supabase, partieId, narratif, cycle, sceneId);

		if (result.success) {
			console.log(`[KG] Extraction OK: ${result.metrics.nb_operations} ops`);
		} else {
			console.warn('[KG] Extraction avec erreurs:', result.metrics.erreurs);
		}

		return result;
	} catch (err) {
		console.error('[KG] Erreur extraction:', err);
		return null;
	}
}

// ============================================================================
// UTILITAIRES
// ============================================================================

/**
 * Récupère ou crée la scène en cours
 */
export async function ensureSceneExists(supabase, partieId, cycle, lieu, heure) {
	let scene = await getSceneEnCours(supabase, partieId);

	if (!scene && lieu) {
		console.log(`[SCENE] Création première scène: ${lieu}`);
		scene = await creerScene(supabase, partieId, cycle, lieu, heure);
	}

	return scene;
}
