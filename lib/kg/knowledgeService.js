/**
 * Service Connaissances pour LDVELH
 * Gère les croyances de Valentin vs la réalité
 */

import { withCache, cacheInvalidate } from '../cache/sessionCache.js';
import { trouverEntite, getEntite } from './kgService.js';

// ============================================================================
// CONSTANTES
// ============================================================================

const CERTITUDES = ['certain', 'croit', 'soupconne', 'rumeur', 'devine'];
const IMPACTS_REVELATION = ['mineur', 'significatif', 'majeur', 'devastateur'];

const ATTRIBUTS_PAR_TYPE = {
	personnage: ['metier', 'vrai_nom', 'secret', 'affiliation', 'intention', 'origine', 'age_reel', 'situation_familiale', 'passé'],
	lieu: ['proprietaire', 'activite_cachee', 'histoire', 'secret'],
	organisation: ['vrai_but', 'membres_secrets', 'activites_illegales', 'dirigeant_reel'],
	objet: ['origine', 'valeur_reelle', 'pouvoir_cache', 'ancien_proprietaire']
};

// ============================================================================
// LECTURE
// ============================================================================

/**
 * Récupère toutes les connaissances actives de Valentin
 */
export async function getConnaissances(supabase, partieId) {
	return withCache(partieId, 'connaissances', async () => {
		const { data, error } = await supabase
			.from('kg_v_connaissances_actives')
			.select('*')
			.eq('partie_id', partieId)
			.order('cycle_decouverte', { ascending: false });

		if (error) {
			console.error('[Connaissances] Erreur lecture:', error);
			return [];
		}
		return data || [];
	});
}

/**
 * Récupère les connaissances sur une entité spécifique
 */
export async function getConnaissancesEntite(supabase, partieId, entiteNom) {
	const entiteId = await trouverEntite(supabase, partieId, entiteNom);
	if (!entiteId) return [];

	const { data, error } = await supabase.rpc('kg_get_connaissances_entite', {
		p_partie_id: partieId,
		p_entite_id: entiteId
	});

	if (error) {
		console.error('[Connaissances] Erreur getConnaissancesEntite:', error);
		return [];
	}

	return data || [];
}

/**
 * Récupère les révélations possibles (croyances fausses pas encore révélées)
 * Utile pour le MJ (Sonnet) pour planifier des twists
 */
export async function getRevelationsPossibles(supabase, partieId) {
	const { data, error } = await supabase.rpc('kg_get_revelations_possibles', {
		p_partie_id: partieId
	});

	if (error) {
		console.error('[Connaissances] Erreur getRevelationsPossibles:', error);
		return [];
	}

	return data || [];
}

/**
 * Récupère l'historique des révélations passées
 */
export async function getHistoriqueRevelations(supabase, partieId) {
	const { data, error } = await supabase
		.from('kg_v_revelations')
		.select('*')
		.eq('partie_id', partieId)
		.order('cycle_revelation', { ascending: false });

	if (error) return [];
	return data || [];
}

// ============================================================================
// ÉCRITURE
// ============================================================================

/**
 * Ajoute ou met à jour une connaissance
 */
export async function setConnaissance(supabase, partieId, params) {
	const {
		entite,          // Nom de l'entité
		attribut,        // Type d'attribut
		valeur_percue,   // Ce que Valentin croit
		valeur_reelle,   // La vérité (optionnel, pour planter des twists)
		certitude = 'certain',
		source_info,
		cycle
	} = params;

	// Valider certitude
	if (!CERTITUDES.includes(certitude)) {
		console.warn(`[Connaissances] Certitude invalide: ${certitude}`);
		return null;
	}

	// Trouver l'entité
	const entiteId = await trouverEntite(supabase, partieId, entite);
	if (!entiteId) {
		console.warn(`[Connaissances] Entité non trouvée: ${entite}`);
		return null;
	}

	// Appeler la fonction SQL
	const { data, error } = await supabase.rpc('kg_set_connaissance', {
		p_partie_id: partieId,
		p_entite_id: entiteId,
		p_attribut: attribut,
		p_valeur_percue: valeur_percue,
		p_valeur_reelle: valeur_reelle || null,
		p_certitude: certitude,
		p_source_info: source_info || null,
		p_cycle: cycle
	});

	if (error) {
		console.error('[Connaissances] Erreur setConnaissance:', error);
		return null;
	}

	cacheInvalidate(partieId, 'connaissances');
	console.log(`[Connaissances] ${entite}.${attribut} = "${valeur_percue}" (${certitude})`);

	return data;
}

/**
 * Révèle la vérité sur un attribut (moment dramatique!)
 * Retourne les infos pour générer le narratif de révélation
 */
export async function revelerVerite(supabase, partieId, params) {
	const {
		entite,
		attribut,
		vraie_valeur,
		cycle,
		titre_revelation,
		impact = 'significatif'
	} = params;

	if (!IMPACTS_REVELATION.includes(impact)) {
		console.warn(`[Connaissances] Impact invalide: ${impact}`);
	}

	const { data, error } = await supabase.rpc('kg_reveler_verite', {
		p_partie_id: partieId,
		p_entite_nom: entite,
		p_attribut: attribut,
		p_vraie_valeur: vraie_valeur,
		p_cycle: cycle,
		p_revelation_titre: titre_revelation || null,
		p_revelation_impact: impact
	});

	if (error) {
		console.error('[Connaissances] Erreur revelerVerite:', error);
		return null;
	}

	cacheInvalidate(partieId, 'connaissances');

	const result = data?.[0];
	if (result?.etait_faux) {
		console.log(`[Connaissances] 🎭 RÉVÉLATION: ${entite}.${attribut}`);
		console.log(`  Croyait: "${result.ancienne_croyance}"`);
		console.log(`  Réalité: "${result.nouvelle_verite}"`);
	}

	return result;
}

/**
 * Plante un secret (connaissance fausse que Valentin croit vraie)
 * Le MJ peut l'utiliser pour préparer des twists futurs
 */
export async function planterSecret(supabase, partieId, params) {
	const {
		entite,
		attribut,
		ce_que_val_croit,  // La version "officielle"
		la_verite,         // Ce qui sera révélé plus tard
		source_info,
		cycle
	} = params;

	return setConnaissance(supabase, partieId, {
		entite,
		attribut,
		valeur_percue: ce_que_val_croit,
		valeur_reelle: la_verite,
		certitude: 'certain',
		source_info,
		cycle
	});
}

// ============================================================================
// FORMATAGE POUR CONTEXTE
// ============================================================================

/**
 * Formate les connaissances pour le contexte MJ
 * Inclut les indicateurs de fiabilité
 */
export function formatConnaissancesPourContexte(connaissances, entitesPresentes = []) {
	if (!connaissances?.length) return '';

	// Grouper par entité
	const parEntite = {};
	for (const c of connaissances) {
		if (!parEntite[c.entite_nom]) {
			parEntite[c.entite_nom] = {
				type: c.entite_type,
				connaissances: []
			};
		}
		parEntite[c.entite_nom].connaissances.push(c);
	}

	let output = '=== CE QUE VALENTIN SAIT/CROIT ===\n';

	// Priorité aux entités présentes
	const entitesOrdonnees = [
		...Object.keys(parEntite).filter(n => entitesPresentes.includes(n)),
		...Object.keys(parEntite).filter(n => !entitesPresentes.includes(n))
	];

	for (const nom of entitesOrdonnees) {
		const { type, connaissances: conns } = parEntite[nom];

		output += `\n## ${nom} (${type})\n`;

		for (const c of conns) {
			const fiabilite = formatFiabilite(c.certitude);
			output += `• ${c.attribut}: ${c.valeur_percue}`;
			if (c.certitude !== 'certain') {
				output += ` ${fiabilite}`;
			}
			if (c.source_info) {
				output += ` [${c.source_info}]`;
			}
			output += '\n';
		}
	}

	return output + '\n';
}

function formatFiabilite(certitude) {
	switch (certitude) {
		case 'certain': return '';
		case 'croit': return '(pense)';
		case 'soupconne': return '(soupçonne)';
		case 'rumeur': return '(rumeur)';
		case 'devine': return '(devine)';
		default: return '';
	}
}

/**
 * Formate les révélations possibles pour le MJ
 * (Informations secrètes, pas montrées au joueur)
 */
export function formatRevelationsPourMJ(revelations) {
	if (!revelations?.length) return '';

	let output = '\n=== SECRETS À RÉVÉLER (MJ ONLY) ===\n';
	output += '⚠️ Valentin ne sait PAS encore ceci:\n\n';

	for (const r of revelations) {
		output += `• ${r.entite_nom}.${r.attribut}:\n`;
		output += `  Croit: "${r.valeur_percue}"\n`;
		output += `  Vérité: "${r.valeur_reelle}"\n`;
		output += `  (depuis cycle ${r.cycle_decouverte})\n\n`;
	}

	return output;
}

// ============================================================================
// OPÉRATIONS POUR KGOPERATIONS
// ============================================================================

/**
 * Applique une opération CONNAISSANCE
 * Appelé depuis kgOperations.appliquerOperations
 */
export async function appliquerOpConnaissance(supabase, partieId, op, cycle, resultats) {
	switch (op.op) {
		case 'APPRENDRE':
			await opApprendre(supabase, partieId, op, cycle, resultats);
			break;
		case 'REVELER':
			await opReveler(supabase, partieId, op, cycle, resultats);
			break;
		case 'SOUPCONNER':
			await opSoupconner(supabase, partieId, op, cycle, resultats);
			break;
		case 'PLANTER_SECRET':
			await opPlanterSecret(supabase, partieId, op, cycle, resultats);
			break;
	}
}

async function opApprendre(supabase, partieId, op, cycle, resultats) {
	const result = await setConnaissance(supabase, partieId, {
		entite: op.entite,
		attribut: op.attribut,
		valeur_percue: op.valeur,
		certitude: op.certitude || 'certain',
		source_info: op.source,
		cycle
	});

	if (result) {
		resultats.connaissances_ajoutees = (resultats.connaissances_ajoutees || 0) + 1;
	}
}

async function opReveler(supabase, partieId, op, cycle, resultats) {
	const result = await revelerVerite(supabase, partieId, {
		entite: op.entite,
		attribut: op.attribut,
		vraie_valeur: op.verite,
		cycle,
		titre_revelation: op.titre,
		impact: op.impact || 'significatif'
	});

	if (result?.etait_faux) {
		resultats.revelations = resultats.revelations || [];
		resultats.revelations.push({
			entite: op.entite,
			attribut: op.attribut,
			avant: result.ancienne_croyance,
			apres: result.nouvelle_verite
		});
	}
}

async function opSoupconner(supabase, partieId, op, cycle, resultats) {
	await setConnaissance(supabase, partieId, {
		entite: op.entite,
		attribut: op.attribut,
		valeur_percue: op.valeur,
		certitude: 'soupconne',
		source_info: op.source || 'déduit',
		cycle
	});

	resultats.connaissances_ajoutees = (resultats.connaissances_ajoutees || 0) + 1;
}

async function opPlanterSecret(supabase, partieId, op, cycle, resultats) {
	await planterSecret(supabase, partieId, {
		entite: op.entite,
		attribut: op.attribut,
		ce_que_val_croit: op.facade,
		la_verite: op.verite,
		source_info: op.source,
		cycle
	});

	resultats.secrets_plantes = (resultats.secrets_plantes || 0) + 1;
}

// ============================================================================
// VALIDATION
// ============================================================================

export function validerOpConnaissance(op) {
	if (!op?.op) return { valide: false, raison: 'Opération sans type' };

	const OPS_VALIDES = ['APPRENDRE', 'REVELER', 'SOUPCONNER', 'PLANTER_SECRET'];
	if (!OPS_VALIDES.includes(op.op)) {
		return { valide: false, raison: `Op connaissance invalide: ${op.op}` };
	}

	if (!op.entite) return { valide: false, raison: 'Entité manquante' };
	if (!op.attribut) return { valide: false, raison: 'Attribut manquant' };

	switch (op.op) {
		case 'APPRENDRE':
		case 'SOUPCONNER':
			if (!op.valeur) return { valide: false, raison: 'Valeur manquante' };
			break;
		case 'REVELER':
			if (!op.verite) return { valide: false, raison: 'Vérité manquante' };
			break;
		case 'PLANTER_SECRET':
			if (!op.facade || !op.verite) {
				return { valide: false, raison: 'Façade et vérité requises' };
			}
			break;
	}

	return { valide: true };
}

export { CERTITUDES, IMPACTS_REVELATION, ATTRIBUTS_PAR_TYPE };
