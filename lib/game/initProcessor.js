/**
 * Traitement du mode INIT (création d'une nouvelle partie)
 */

import {
	appliquerOperations,
	trouverEntite,
	getProtagoniste
} from '../kg/kgService.js';
import { creerScene } from '../scene/sceneService.js';

// ============================================================================
// CONFIGURATION
// ============================================================================

const AGE_MIN_ROMANCE = 25;
const AGE_MAX_ROMANCE = 45;

const COMPETENCES_VALENTIN = {
	informatique: 5, systemes: 4, recherche: 4,
	social: 2, cuisine: 3, bricolage: 3,
	observation: 3, culture: 3, sang_froid: 3,
	pedagogie: 3, physique: 3, administration: 3, jeux: 3,
	discretion: 2, negociation: 2, empathie: 2,
	art: 2, commerce: 2, leadership: 2, xenologie: 2,
	medical: 1, pilotage: 1, mensonge: 1, survie: 1,
	intimidation: 1, seduction: 1, droit: 1, botanique: 1
};

const STATS_INITIALES = [
	['energie', '3'],
	['moral', '3'],
	['sante', '5'],
	['credits', '1400']
];

// ============================================================================
// TRAITEMENT PRINCIPAL
// ============================================================================

/**
 * Traite une réponse init et crée le Knowledge Graph initial
 * @param {object} supabase - Client Supabase
 * @param {string} partieId - ID de la partie
 * @param {object} parsed - Réponse Claude parsée
 * @param {number} cycle - Cycle (toujours 1 pour init)
 * @returns {Promise<object>} Résultats du traitement
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

	// Appliquer toutes les opérations
	const resultats = await appliquerOperations(supabase, partieId, operations, cycle);
	console.log(`[INIT] ${resultats.entites_creees} entités, ${resultats.relations_creees} relations`);

	// États initiaux de Valentin
	await initValentinStats(supabase, partieId, cycle);

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

	// Créer la première scène
	let sceneId = null;
	if (parsed.lieu_actuel) {
		const scene = await creerScene(supabase, partieId, 1, parsed.lieu_actuel, parsed.heure);
		sceneId = scene?.id;
	}

	return {
		...resultats,
		sceneId
	};
}

// ============================================================================
// BUILDERS D'OPÉRATIONS
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

	// Lier à la station si existe
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

	// Lier au secteur ou à la station
	const parent = lieu.secteur || mondeNom;
	if (parent) {
		ops.push({
			op: 'CREER_RELATION',
			source: lieu.nom,
			cible: parent,
			type: 'situe_dans'
		});
	}

	// Relations "frequente" pour les PNJ fréquents
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
		age >= AGE_MIN_ROMANCE &&
		age <= AGE_MAX_ROMANCE
	);

	const ops = [
		{
			op: 'CREER_ENTITE',
			type: 'personnage',
			nom: pnj.nom,
			alias: [pnj.nom.split(' ')[0]], // Prénom comme alias
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

	// Domicile
	if (pnj.domicile) {
		ops.push({
			op: 'CREER_RELATION',
			source: pnj.nom,
			cible: pnj.domicile,
			type: 'habite'
		});
	}

	// Arcs personnels
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

	// Lier les PNJ impliqués
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
// INITIALISATION DES ÉTATS
// ============================================================================

async function initValentinStats(supabase, partieId, cycle) {
	const protagoniste = await getProtagoniste(supabase, partieId);
	if (!protagoniste) return;

	await Promise.all(
		STATS_INITIALES.map(([attr, val]) =>
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
