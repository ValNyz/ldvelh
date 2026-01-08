/**
 * Gestion de l'état du jeu
 * Structure unifiée : {partie, valentin, ia}
 */

import { STATS_VALENTIN_DEFAUT } from '../constants.js';
import {
	getProtagoniste,
	getStatsValentin,
	getInventaire
} from '../kg/kgService.js';

// ============================================================================
// STRUCTURE DU STATE CLIENT
// ============================================================================
/**
 * Structure normalisée du gameState :
 * {
 *   partie: {
 *     cycle_actuel: number,
 *     jour: string,
 *     date_jeu: string,
 *     heure: string,
 *     lieu_actuel: string,
 *     pnjs_presents: string[],
 *     nom?: string
 *   },
 *   valentin: {
 *     energie: number,
 *     moral: number,
 *     sante: number,
 *     credits: number,
 *     inventaire: InventaireItem[]
 *   },
 *   ia: { nom: string, ... } | null
 * }
 */

// ============================================================================
// CHARGEMENT ÉTAT (DEPUIS SUPABASE)
// ============================================================================

/**
 * Charge l'état complet d'une partie depuis la BDD
 */
export async function loadGameState(supabase, partieId) {
	const [partie, protagoniste, stats, inventaireRaw, iaData] = await Promise.all([
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

	const inventaire = formatInventaireForClient(inventaireRaw);

	return {
		partie: {
			cycle_actuel: partie?.cycle_actuel || 1,
			jour: partie?.jour,
			date_jeu: partie?.date_jeu,
			heure: partie?.heure,
			lieu_actuel: partie?.lieu_actuel,
			pnjs_presents: partie?.pnjs_presents || [],
			nom: partie?.nom
		},
		valentin: {
			...(protagoniste?.proprietes || {}),
			...stats,
			inventaire
		},
		ia: iaData ? { nom: iaData.nom, ...iaData.proprietes } : null
	};
}

/**
 * Charge les messages d'une partie
 */
export async function loadChatMessages(supabase, partieId) {
	const { data, error } = await supabase
		.from('chat_messages')
		.select('role, content, cycle, jour, date_jeu, lieu, pnjs_presents, created_at')
		.eq('partie_id', partieId)
		.order('created_at', { ascending: true });

	if (error) {
		console.error('[LOAD] Erreur chargement messages:', error);
		return [];
	}

	return data || [];
}

// ============================================================================
// FORMATAGE INVENTAIRE POUR CLIENT
// ============================================================================

export function formatInventaireForClient(inventaireRaw) {
	if (!inventaireRaw?.length) return [];

	return inventaireRaw.map(item => ({
		id: item.objet_id,
		nom: item.objet_nom,
		quantite: item.quantite || 1,
		localisation: item.localisation || 'sur_soi',
		categorie: item.categorie || item.objet_props?.categorie || 'autre',
		etat: item.etat || 'bon',
		valeur_neuve: item.valeur_neuve || 0,
		prete_a: item.prete_a || null
	}));
}

export function getInventaireNoms(inventaire) {
	if (!inventaire?.length) return [];
	if (typeof inventaire[0] === 'string') return inventaire;
	return inventaire.map(i => i.nom);
}

// ============================================================================
// CONSTRUCTION STATE CLIENT (DEPUIS RÉPONSE CLAUDE)
// ============================================================================

/**
 * Construit le state initial après traitement init (World Builder)
 * 
 * NOTE: En mode World Builder, l'init ne génère plus de narratif.
 * Les données temporelles sont maintenant dans evenement_arrivee.
 */
export function buildClientStateFromInit(parsed) {
	const evt = parsed.evenement_arrivee || {};

	return {
		partie: {
			cycle_actuel: evt.cycle || 1,
			jour: evt.jour,
			date_jeu: evt.date_jeu,
			heure: evt.heure || '08h00',
			lieu_actuel: evt.lieu_actuel,
			pnjs_presents: [] // Personne n'est présent avant le premier LIGHT
		},
		valentin: getDefaultValentinStats(),
		ia: parsed.ia || null,
		// Flags pour le client
		monde_cree: true,
		attente_premier_narratif: true
	};
}

/**
 * Construit le state à envoyer au client après traitement light
 */
export async function buildClientStateFromLight(supabase, partieId, parsed, currentCycle) {
	const [partieData, stats, inventaireRaw] = await Promise.all([
		supabase.from('parties')
			.select('jour, date_jeu, nom')
			.eq('id', partieId)
			.single()
			.then(r => r.data),

		getStatsValentin(supabase, partieId),
		getInventaire(supabase, partieId)
	]);

	const inventaire = formatInventaireForClient(inventaireRaw);

	return {
		partie: {
			cycle_actuel: parsed.nouveau_cycle ? currentCycle + 1 : currentCycle,
			jour: parsed.nouveau_jour?.jour || partieData?.jour,
			date_jeu: parsed.nouveau_jour?.date_jeu || partieData?.date_jeu,
			heure: parsed.heure,
			lieu_actuel: parsed.lieu_actuel,
			pnjs_presents: parsed.pnjs_presents || [],
			nom: partieData?.nom
		},
		valentin: {
			...stats,
			inventaire
		},
		ia: null
	};
}

// ============================================================================
// NORMALISATION
// ============================================================================

export function normalizeGameState(rawState) {
	if (!rawState) return null;

	if (rawState.partie) {
		return {
			partie: {
				cycle_actuel: rawState.partie.cycle_actuel || 1,
				jour: rawState.partie.jour,
				date_jeu: rawState.partie.date_jeu,
				heure: rawState.partie.heure,
				lieu_actuel: rawState.partie.lieu_actuel,
				pnjs_presents: rawState.partie.pnjs_presents || [],
				nom: rawState.partie.nom
			},
			valentin: normalizeValentin(rawState.valentin),
			ia: rawState.ia || null
		};
	}

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
			valentin: normalizeValentin(rawState.valentin),
			ia: rawState.ia || null
		};
	}

	return null;
}

export function getDefaultValentinStats() {
	return {
		...STATS_VALENTIN_DEFAUT,
		inventaire: []
	};
}

export function normalizeValentin(valentin) {
	if (!valentin) return getDefaultValentinStats();

	return {
		energie: valentin.energie ?? STATS_VALENTIN_DEFAUT.energie,
		moral: valentin.moral ?? STATS_VALENTIN_DEFAUT.moral,
		sante: valentin.sante ?? STATS_VALENTIN_DEFAUT.sante,
		credits: valentin.credits ?? STATS_VALENTIN_DEFAUT.credits,
		inventaire: normalizeInventaire(valentin.inventaire)
	};
}

export function normalizeInventaire(inventaire) {
	if (!inventaire?.length) return [];

	if (typeof inventaire[0] === 'string') {
		return inventaire.map(nom => ({
			nom,
			quantite: 1,
			localisation: 'sur_soi',
			categorie: 'autre',
			etat: 'bon',
			valeur_neuve: 0,
			prete_a: null
		}));
	}

	return inventaire.map(item => ({
		id: item.id,
		nom: item.nom || item.objet_nom,
		quantite: item.quantite || 1,
		localisation: item.localisation || 'sur_soi',
		categorie: item.categorie || 'autre',
		etat: item.etat || 'bon',
		valeur_neuve: item.valeur_neuve || 0,
		prete_a: item.prete_a || null
	}));
}

// ============================================================================
// SNAPSHOT POUR ROLLBACK
// ============================================================================

export async function createStateSnapshot(supabase, partieId) {
	const { data } = await supabase
		.from('parties')
		.select('cycle_actuel, jour, date_jeu, heure, lieu_actuel, pnjs_presents')
		.eq('id', partieId)
		.single();

	return data;
}

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
