/**
 * Gestion de l'état du jeu
 */

import {
	getProtagoniste,
	getStatsValentin,
	getInventaire
} from '../kg/kgService.js';

// ============================================================================
// CHARGEMENT ÉTAT
// ============================================================================

/**
 * Charge l'état complet d'une partie depuis la BDD
 * @param {object} supabase - Client Supabase
 * @param {string} partieId - ID de la partie
 * @returns {Promise<object>} État du jeu
 */
export async function loadGameState(supabase, partieId) {
	// Requêtes parallèles
	const [partie, protagoniste, stats, inventaire, iaData] = await Promise.all([
		supabase.from('parties')
			.select('*')
			.eq('id', partieId)
			.single()
			.then(r => r.data),

		getProtagoniste(supabase, partieId),
		getStatsValentin(supabase, partieId),
		getInventaire(supabase, partieId),

		supabase.from('kg_entites')
			.select('nom, proprietes')
			.eq('partie_id', partieId)
			.eq('type', 'ia')
			.single()
			.then(r => r.data)
			.catch(() => null)
	]);

	return {
		partie,
		valentin: {
			...(protagoniste?.proprietes || {}),
			...stats,
			inventaire: inventaire.map(i => i.objet_nom)
		},
		ia: iaData ? { nom: iaData.nom, ...iaData.proprietes } : null
	};
}

/**
 * Charge les messages d'une partie
 */
export async function loadChatMessages(supabase, partieId) {
	const { data } = await supabase
		.from('chat_messages')
		.select('role, content, cycle, scene_id, created_at')
		.eq('partie_id', partieId)
		.order('created_at', { ascending: true });

	return data || [];
}

// ============================================================================
// NORMALISATION
// ============================================================================

/**
 * Normalise un gameState depuis différentes sources
 * (Supabase, réponse Claude, client)
 * @param {object} rawState - État brut
 * @returns {object|null} État normalisé
 */
export function normalizeGameState(rawState) {
	if (!rawState) return null;

	// Depuis loadGameState (Supabase) - a déjà la structure partie/valentin
	if (rawState.partie) {
		return {
			partie: {
				cycle_actuel: rawState.partie.cycle_actuel || 1,
				jour: rawState.partie.jour,
				date_jeu: rawState.partie.date_jeu,
				heure: rawState.partie.heure,
				lieu_actuel: rawState.partie.lieu_actuel,
				pnjs_presents: rawState.partie.pnjs_presents || []
			},
			valentin: rawState.valentin || getDefaultValentinStats(),
			ia: rawState.ia || null
		};
	}

	// Depuis réponse Claude (cycle à la racine)
	if (rawState.cycle !== undefined || rawState.lieu_actuel) {
		return {
			partie: {
				cycle_actuel: rawState.cycle || 1,
				jour: rawState.jour,
				date_jeu: rawState.date_jeu,
				heure: rawState.heure,
				lieu_actuel: rawState.lieu_actuel,
				pnjs_presents: rawState.pnjs_presents || []
			},
			valentin: rawState.valentin || getDefaultValentinStats(),
			ia: rawState.ia || null
		};
	}

	return null;
}

/**
 * Stats par défaut de Valentin
 */
export function getDefaultValentinStats() {
	return {
		energie: 3,
		moral: 3,
		sante: 5,
		credits: 1400,
		inventaire: []
	};
}

// ============================================================================
// CONSTRUCTION STATE CLIENT
// ============================================================================

/**
 * Construit le state à envoyer au client après traitement init
 */
export function buildClientStateFromInit(parsed) {
	return {
		cycle: parsed.cycle || 1,
		jour: parsed.jour,
		date_jeu: parsed.date_jeu,
		heure: parsed.heure,
		lieu_actuel: parsed.lieu_actuel,
		pnjs_presents: parsed.pnjs_presents || [],
		valentin: getDefaultValentinStats(),
		ia: parsed.ia || null
	};
}

/**
 * Construit le state à envoyer au client après traitement light
 */
export async function buildClientStateFromLight(supabase, partieId, parsed, currentCycle) {
	// Récupérer les données mises à jour
	const [partieData, stats, inventaire] = await Promise.all([
		supabase.from('parties')
			.select('jour, date_jeu')
			.eq('id', partieId)
			.single()
			.then(r => r.data),

		getStatsValentin(supabase, partieId),
		getInventaire(supabase, partieId)
	]);

	return {
		cycle: parsed.nouveau_cycle ? currentCycle + 1 : currentCycle,
		jour: parsed.nouveau_jour?.jour || partieData?.jour,
		date_jeu: parsed.nouveau_jour?.date_jeu || partieData?.date_jeu,
		heure: parsed.heure,
		lieu_actuel: parsed.lieu_actuel,
		pnjs_presents: parsed.pnjs_presents || [],
		valentin: {
			...stats,
			inventaire: inventaire.map(i => i.objet_nom)
		}
	};
}

// ============================================================================
// SNAPSHOT POUR ROLLBACK
// ============================================================================

/**
 * Crée un snapshot de l'état pour permettre le rollback
 */
export async function createStateSnapshot(supabase, partieId) {
	const { data } = await supabase
		.from('parties')
		.select('cycle_actuel, jour, date_jeu, heure, lieu_actuel, pnjs_presents')
		.eq('id', partieId)
		.single();

	return data;
}

/**
 * Restaure un snapshot
 */
export async function restoreStateSnapshot(supabase, partieId, snapshot) {
	if (!snapshot) return;

	await supabase
		.from('parties')
		.update({
			cycle_actuel: snapshot.cycle_actuel,
			jour: snapshot.jour,
			date_jeu: snapshot.date_jeu,
			heure: snapshot.heure,
			lieu_actuel: snapshot.lieu_actuel,
			pnjs_presents: snapshot.pnjs_presents
		})
		.eq('id', partieId);
}

// ============================================================================
// MISE À JOUR PARTIE
// ============================================================================

/**
 * Met à jour les infos de base de la partie
 */
export async function updatePartieBasics(supabase, partieId, updates) {
	const { error } = await supabase
		.from('parties')
		.update(updates)
		.eq('id', partieId);

	if (error) {
		console.error('[STATE] Erreur mise à jour partie:', error);
		throw error;
	}
}

/**
 * Passe au cycle suivant
 */
export async function advanceCycle(supabase, partieId, currentCycle, nouveauJour) {
	await supabase
		.from('parties')
		.update({
			cycle_actuel: currentCycle + 1,
			jour: nouveauJour?.jour,
			date_jeu: nouveauJour?.date_jeu
		})
		.eq('id', partieId);
}
