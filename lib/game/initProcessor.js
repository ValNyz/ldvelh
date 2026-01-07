/**
 * Traitement du mode INIT (création d'une nouvelle partie)
 * 
 */

import {
	ROMANCE,
	COMPETENCES_VALENTIN,
	STATS_VALENTIN_DEFAUT
} from '../constants.js';
import {
	trouverEntite,
	getProtagoniste
} from '../kg/kgService.js';
import { appliquerOperations } from '../kg/kgOperations.js'

// ============================================================================
// IMPORT INVENTAIRE INITIAL
// ============================================================================

import {
	determinerSituation,
	genererOperationsInventaire,
	SITUATIONS_DEPART
} from './initialInventory.js';

// ============================================================================
// CONFIGURATION
// ============================================================================


// ============================================================================
// TRAITEMENT PRINCIPAL
// ============================================================================

/**
 * Traite une réponse init et crée le Knowledge Graph initial
 */
export async function processInitMode(supabase, partieId, parsed, cycle = 1) {
	console.log('[INIT] Création du Knowledge Graph initial');

	const operations = [];

	// 1. Protagoniste (Valentin)
	operations.push(buildValentinOperation(parsed));

	// 2. IA personnelle
	if (parsed.ia?.nom) {
		operations.push(...buildIAOperations(parsed.ia.nom));
	}

	// 3. Monde (station/base)
	if (parsed.monde) {
		operations.push(buildMondeOperation(parsed.monde));
	}

	// 4. Employeur
	if (parsed.employeur) {
		operations.push(...buildEmployeurOperations(parsed));
	}

	// 5. Lieux initiaux
	for (const lieu of (parsed.lieux_initiaux || [])) {
		operations.push(...buildLieuOperations(lieu, parsed.monde?.nom));
	}

	// 6. PNJ initiaux
	for (const pnj of (parsed.pnj_initiaux || [])) {
		operations.push(...buildPnjOperations(pnj));
	}

	// 7. Arcs narratifs
	for (const arc of (parsed.arcs_potentiels || [])) {
		operations.push(...buildArcOperations(arc));
	}

	// Appliquer toutes les opérations de base
	const resultats = await appliquerOperations(supabase, partieId, operations, cycle);
	console.log(`[INIT] ${resultats.entites_creees} entités, ${resultats.relations_creees} relations`);

	// ============================================================================
	// 8. INVENTAIRE INITIAL (NOUVEAU)
	// ============================================================================

	const raisonDepart = parsed.valentin?.raison_depart || '';
	const situation = determinerSituation(raisonDepart);

	// Crédits : utiliser ceux fournis par Claude OU ceux de la situation
	const creditsInitiaux = parsed.credits_initiaux
		|| parsed.valentin?.credits_initiaux
		|| SITUATIONS_DEPART[situation]?.credits
		|| STATS_VALENTIN_DEFAUT.credits;

	console.log(`[INIT] Situation: ${situation}, Crédits: ${creditsInitiaux}`);

	// Si Claude a fourni un inventaire initial, l'utiliser
	if (parsed.inventaire_initial?.length > 0) {
		const inventaireOps = [];

		for (const item of parsed.inventaire_initial) {
			inventaireOps.push({
				op: 'CREER_ENTITE',
				type: 'objet',
				nom: item.nom,
				proprietes: {
					categorie: item.categorie || 'equipement',
					valeur_neuve: item.valeur || 0,
					prix_achat: item.valeur || 0,
					etat: item.etat || 'bon',
					description: item.description || null
				}
			});

			inventaireOps.push({
				op: 'CREER_RELATION',
				source: 'Valentin',
				cible: item.nom,
				type: 'possede',
				proprietes: {
					quantite: item.quantite || 1,
					depuis_cycle: cycle,
					localisation: normaliserLocalisation(item.localisation),
					origine: 'initial'
				}
			});
		}

		const invResult = await appliquerOperations(supabase, partieId, inventaireOps, cycle);
		console.log(`[INIT] Inventaire Claude: ${invResult.entites_creees} objets`);

	} else {
		// Sinon, utiliser l'inventaire par défaut de la situation
		const { operations: invOps } = genererOperationsInventaire(situation, cycle);

		if (invOps.length > 0) {
			const invResult = await appliquerOperations(supabase, partieId, invOps, cycle);
			console.log(`[INIT] Inventaire défaut (${situation}): ${invResult.entites_creees} objets`);
		}
	}

	// ============================================================================
	// 9. ÉTATS INITIAUX
	// ============================================================================

	// Stats Valentin avec crédits dynamiques
	await initValentinStats(supabase, partieId, cycle, creditsInitiaux);

	// États initiaux des PNJ
	await initPnjStats(supabase, partieId, parsed.pnj_initiaux || [], cycle);

	// Mettre à jour la partie
	await supabase.from('parties').update({
		cycle_actuel: parsed.cycle || 1,
		jour: parsed.jour,
		date_jeu: parsed.date_jeu,
		heure: parsed.heure,
		lieu_actuel: parsed.lieu_actuel
	}).eq('id', partieId);

	return {
		...resultats,
		situation,
		credits: creditsInitiaux
	};
}

// ============================================================================
// HELPERS
// ============================================================================

/**
 * Normalise les localisations pour la cohérence
 */
function normaliserLocalisation(loc) {
	if (!loc) return 'sur_soi';

	const locLower = loc.toLowerCase();

	// Mappings communs
	const mappings = {
		'sur soi': 'sur_soi',
		'poche': 'sur_soi',
		'poches': 'sur_soi',
		'sac': 'sac_a_dos',
		'sac à dos': 'sac_a_dos',
		'sac a dos': 'sac_a_dos',
		'valise': 'valise',
		'appartement': 'appartement',
		'chez soi': 'appartement',
		'bureau': 'bureau',
		'travail': 'bureau'
	};

	return mappings[locLower] || loc;
}

// ============================================================================
// BUILDERS D'OPÉRATIONS (INCHANGÉS)
// ============================================================================

function buildValentinOperation(parsed) {
	return {
		op: 'CREER_ENTITE',
		type: 'protagoniste',
		nom: 'Valentin',
		alias: ['Valentin Nyzam'],
		proprietes: {
			physique: '1m78, brun dégarni, barbe, implants rétiniens',
			traits: ['introverti', 'maladroit en amour', 'curieux', 'romantique malgré lui'],
			raison_depart: parsed.valentin?.raison_depart || null,
			poste: parsed.valentin?.poste || null,
			hobbies: parsed.valentin?.hobbies || ['cuisine'],
			competences: COMPETENCES_VALENTIN
		}
	};
}

function buildIAOperations(iaNom) {
	return [
		{
			op: 'CREER_ENTITE',
			type: 'ia',
			nom: iaNom,
			proprietes: {
				traits: ['sarcastique', 'pragmatique'],
				voix: 'grave, sensuelle'
			}
		},
		{
			op: 'CREER_RELATION',
			source: iaNom,
			cible: 'Valentin',
			type: 'assiste'
		}
	];
}

function buildMondeOperation(monde) {
	return {
		op: 'CREER_ENTITE',
		type: 'lieu',
		nom: monde.nom,
		proprietes: {
			niveau: 'zone',
			type_lieu: monde.type,
			ambiance: monde.ambiance,
			population: monde.population,
			orbite: monde.orbite
		}
	};
}

function buildEmployeurOperations(parsed) {
	const ops = [
		{
			op: 'CREER_ENTITE',
			type: 'organisation',
			nom: parsed.employeur.nom,
			proprietes: {
				type_org: 'entreprise',
				domaine: parsed.employeur.type
			}
		},
		{
			op: 'CREER_RELATION',
			source: 'Valentin',
			cible: parsed.employeur.nom,
			type: 'employe_de',
			proprietes: { poste: parsed.valentin?.poste }
		}
	];

	if (parsed.monde?.nom) {
		ops.push({
			op: 'CREER_RELATION',
			source: parsed.employeur.nom,
			cible: parsed.monde.nom,
			type: 'siege_de'
		});
	}

	return ops;
}

function buildLieuOperations(lieu, mondeNom) {
	const ops = [
		{
			op: 'CREER_ENTITE',
			type: 'lieu',
			nom: lieu.nom,
			proprietes: {
				niveau: 'lieu',
				type_lieu: lieu.type,
				ambiance: lieu.description,
				horaires: lieu.horaires
			}
		}
	];

	const parent = lieu.secteur || mondeNom;
	if (parent) {
		ops.push({
			op: 'CREER_RELATION',
			source: lieu.nom,
			cible: parent,
			type: 'situe_dans'
		});
	}

	for (const freq of (lieu.pnjs_frequents || [])) {
		ops.push({
			op: 'CREER_RELATION',
			source: freq.pnj,
			cible: lieu.nom,
			type: 'frequente',
			proprietes: {
				regularite: freq.regularite || 'parfois',
				periode: freq.periode || 'aléatoire'
			}
		});
	}

	return ops;
}

function buildPnjOperations(pnj) {
	const sexe = (pnj.sexe || '').toUpperCase();
	const age = pnj.age || 0;
	const interetRomantique = (
		sexe === 'F' &&
		age >= ROMANCE.AGE_MIN &&
		age <= ROMANCE.AGE_MAX
	);

	const ops = [
		{
			op: 'CREER_ENTITE',
			type: 'personnage',
			nom: pnj.nom,
			alias: [pnj.nom.split(' ')[0]],
			proprietes: {
				sexe,
				age,
				espece: pnj.espece || 'humain',
				metier: pnj.metier,
				physique: pnj.physique,
				traits: pnj.traits || [],
				interet_romantique: interetRomantique
			}
		},
		{
			op: 'CREER_RELATION',
			source: 'Valentin',
			cible: pnj.nom,
			type: 'connait',
			proprietes: {
				niveau: 0,
				...(interetRomantique && { etape_romantique: 0 })
			}
		}
	];

	if (pnj.domicile) {
		ops.push({
			op: 'CREER_RELATION',
			source: pnj.nom,
			cible: pnj.domicile,
			type: 'habite'
		});
	}

	for (const arcTitre of (pnj.arcs || [])) {
		ops.push(
			{
				op: 'CREER_ENTITE',
				type: 'arc_narratif',
				nom: arcTitre,
				proprietes: {
					type_arc: 'pnj_personnel',
					description: `Arc personnel de ${pnj.nom}`,
					progression: 0,
					etat: 'actif'
				}
			},
			{
				op: 'CREER_RELATION',
				source: pnj.nom,
				cible: arcTitre,
				type: 'implique_dans',
				proprietes: { role: 'protagoniste' }
			}
		);
	}

	return ops;
}

function buildArcOperations(arc) {
	const ops = [
		{
			op: 'CREER_ENTITE',
			type: 'arc_narratif',
			nom: arc.nom,
			proprietes: {
				type_arc: arc.type,
				description: arc.description,
				obstacles: arc.obstacles || [],
				progression: 0,
				etat: 'actif'
			}
		}
	];

	for (const pnjNom of (arc.pnjs_impliques || [])) {
		ops.push({
			op: 'CREER_RELATION',
			source: pnjNom,
			cible: arc.nom,
			type: 'implique_dans'
		});
	}

	return ops;
}

// ============================================================================
// INITIALISATION DES ÉTATS (MODIFIÉ)
// ============================================================================

async function initValentinStats(supabase, partieId, cycle, creditsInitiaux) {
	const protagoniste = await getProtagoniste(supabase, partieId);
	if (!protagoniste) return;

	// Stats avec crédits dynamiques
	const statsInitiales = [
		['energie', STATS_VALENTIN_DEFAUT.energie],
		['moral', STATS_VALENTIN_DEFAUT.moral],
		['sante', STATS_VALENTIN_DEFAUT.sante],
		['credits', creditsInitiaux]
	];

	await Promise.all(
		statsInitiales.map(([attr, val]) =>
			supabase.rpc('kg_set_etat', {
				p_partie_id: partieId,
				p_entite_id: protagoniste.id,
				p_attribut: attr,
				p_valeur: val,
				p_cycle: cycle,
				p_details: null,
				p_certitude: 'certain',
				p_verite: true
			})
		)
	);
}

async function initPnjStats(supabase, partieId, pnjList, cycle) {
	await Promise.all(
		pnjList.map(async (pnj) => {
			const pnjId = await trouverEntite(supabase, partieId, pnj.nom, 'personnage');
			if (!pnjId) return;

			return supabase.rpc('kg_set_etat', {
				p_partie_id: partieId,
				p_entite_id: pnjId,
				p_attribut: 'disposition',
				p_valeur: 'neutre',
				p_cycle: cycle,
				p_details: null,
				p_certitude: 'certain',
				p_verite: true
			});
		})
	);
}
