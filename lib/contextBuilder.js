/**
 * Context Builder pour LDVELH — Version Knowledge Graph
 * Construit le contexte pour Claude Sonnet depuis le KG
 */

import {
	getProtagoniste,
	getIA,
	getEntite,
	getPersonnages,
	getLieux,
	getLieuAvecHierarchie,
	getRelationsValentin,
	getRelationsEntite,
	getInventaire,
	getStatsValentin,
	getEtatsEntite,
	getEvenementsCycle,
	getEvenementsAVenir,
	getEvenementsEntite,
	trouverEntite,
	getEntitesParType,
	getArcsPnj,
	getPnjsFrequentsLieu
} from './kgService.js';
import { getSceneEnCours, getMessagesScene, getScenesAnalyseesCycle } from './sceneService.js';

// ============================================================================
// CONFIGURATION
// ============================================================================

const CONFIG = {
	MAX_PERSONNAGES_FICHES: 10,
	MAX_EVENEMENTS_RECENTS: 8,
	MAX_EVENEMENTS_A_VENIR: 5,
	MAX_MESSAGES_SCENE: 30,
	CYCLES_RECENTS: 3
};

// ============================================================================
// FORMATAGE — SITUATION
// ============================================================================

function formatSituation(partie, lieu, hierarchieLieu, pnjsFrequents = []) {
	let output = '=== SITUATION ===\n';

	// Date et heure
	if (partie?.jour || partie?.date_jeu) {
		output += `${partie.jour || ''} ${partie.date_jeu || ''}\n`;
	}
	if (partie?.heure) {
		output += `Heure: ${partie.heure}\n`;
	}

	// Lieu avec hiérarchie
	if (lieu) {
		output += `Lieu: ${lieu.nom}`;
		const props = lieu.proprietes || {};
		if (props.type_lieu) output += ` (${props.type_lieu})`;
		if (hierarchieLieu?.parent) {
			output += ` — ${hierarchieLieu.parent.nom}`;
		}
		output += '\n';
		if (props.ambiance) output += `Ambiance: ${props.ambiance}\n`;
	} else if (partie?.lieu_actuel) {
		output += `Lieu: ${partie.lieu_actuel}\n`;
	}

	// PNJ fréquents (passés en paramètre maintenant)
	if (pnjsFrequents.length > 0) {
		output += 'PNJ fréquents ici: ';
		output += pnjsFrequents.map(f => {
			let str = f.nom;
			if (f.periode && f.periode !== 'aléatoire') str += ` (${f.periode})`;
			return str;
		}).join(', ');
		output += '\n';
	}

	return output + '\n';
}

// ============================================================================
// FORMATAGE — VALENTIN
// ============================================================================

function formatValentin(protagoniste, ia, stats, inventaire) {
	let output = '=== VALENTIN ===\n';

	// Stats
	output += `Énergie: ${stats.energie}/5 | Moral: ${stats.moral}/5 | Santé: ${stats.sante}/5\n`;
	output += `Crédits: ${stats.credits}\n`;

	// Inventaire
	if (inventaire?.length > 0) {
		const items = inventaire.map(i => {
			if (i.quantite > 1) return `${i.objet_nom} (x${i.quantite})`;
			return i.objet_nom;
		});
		output += `Inventaire: ${items.join(', ')}\n`;
	}

	// Compétences clés (seulement les plus utiles)
	const comp = protagoniste?.proprietes?.competences || {};
	const compCles = ['informatique', 'social', 'cuisine', 'bricolage', 'observation', 'empathie'];
	const compStr = compCles
		.filter(c => comp[c] !== undefined)
		.map(c => `${c.slice(0, 3).toUpperCase()} ${comp[c]}`)
		.join(', ');
	if (compStr) output += `Compétences: ${compStr}\n`;

	// Poste
	if (protagoniste?.proprietes?.poste) {
		output += `Poste: ${protagoniste.proprietes.poste}\n`;
	}

	// IA
	if (ia?.nom) {
		output += `IA: ${ia.nom}`;
		if (ia.proprietes?.traits?.length > 0) {
			output += ` (${ia.proprietes.traits.join(', ')})`;
		}
		output += '\n';
	}

	return output + '\n';
}

// ============================================================================
// FORMATAGE — PNJ PRÉSENTS (fiches complètes)
// ============================================================================

function formatPnjPresent(personnage, relation, etats, arcs = []) {
	const props = personnage.proprietes || {};
	const relProps = relation?.proprietes || {};
	const niveau = relProps.niveau ?? 0;
	const disposition = etats.disposition?.valeur || 'neutre';

	let fiche = `## ${personnage.nom.toUpperCase()} (rel: ${niveau}/10, ${disposition})\n`;

	// Infos de base
	const infos = [];
	if (props.sexe) infos.push(props.sexe === 'F' ? '♀' : (props.sexe === 'M' ? '♂' : '⚬'));
	if (props.age) infos.push(`${props.age} ans`);
	if (props.espece && props.espece !== 'humain') infos.push(props.espece);
	if (props.metier) infos.push(props.metier);
	if (infos.length > 0) fiche += `${infos.join(', ')}\n`;

	// Physique
	if (props.physique) fiche += `Physique: ${props.physique}\n`;

	// Traits
	if (props.traits?.length > 0) fiche += `Traits: ${props.traits.join(', ')}\n`;

	// Stats PNJ
	const statSocial = etats.stat_social?.valeur || '3';
	const statTravail = etats.stat_travail?.valeur || '3';
	const statSante = etats.stat_sante?.valeur || '3';
	fiche += `Stats: Social ${statSocial}/5, Travail ${statTravail}/5, Santé ${statSante}/5\n`;

	// Étape romantique — seulement si intérêt romantique ET progression > 0
	if (props.interet_romantique && relProps.etape_romantique !== undefined) {
		const etapes = ['Inconnus', 'Indifférence', 'Reconnaissance', 'Sympathie', 'Curiosité', 'Intérêt', 'Attirance'];
		fiche += `Romance: ${relProps.etape_romantique}/6 (${etapes[relProps.etape_romantique] || '?'})\n`;
	}

	// Arcs personnels du PNJ (passés en paramètre maintenant)
	if (arcs.length > 0) {
		const arcsStr = arcs
			.filter(a => a.etat === 'actif')
			.map(a => `${a.nom} (${a.progression}%)`)
			.join(', ');
		if (arcsStr) fiche += `Arcs personnels: ${arcsStr}\n`;
	}

	// Humeur actuelle si différente de disposition
	if (etats.humeur?.valeur && etats.humeur.valeur !== disposition) {
		fiche += `Humeur: ${etats.humeur.valeur}\n`;
	}

	return fiche;
}

// ============================================================================
// FORMATAGE — PNJ CONNUS (fiches minimales)
// ============================================================================

function formatPnjConnu(personnage, relation) {
	const props = personnage.proprietes || {};
	const relProps = relation?.proprietes || {};
	const niveau = relProps.niveau ?? 0;

	// Symbole sexe
	const sexeSymbol = props.sexe === 'F' ? '♀' : (props.sexe === 'M' ? '♂' : '');

	let ligne = `• ${personnage.nom} ${sexeSymbol} — rel: ${niveau}/10`;
	if (props.metier) ligne += `, ${props.metier}`;

	// Indicateur discret si intérêt romantique avec progression
	if (props.interet_romantique && relProps.etape_romantique > 1) {
		ligne += ` ♡${relProps.etape_romantique}`;
	}

	return ligne;
}

// ============================================================================
// FORMATAGE — ÉVÉNEMENTS
// ============================================================================

function formatEvenementsRecents(evenements) {
	if (!evenements?.length) return '';

	let output = '=== ÉVÉNEMENTS RÉCENTS ===\n';

	for (const evt of evenements) {
		output += `• [Cycle ${evt.cycle}`;
		if (evt.heure) output += ` ${evt.heure}`;
		output += `] ${evt.titre}`;
		if (evt.participants?.length > 0) {
			const autres = evt.participants.filter(p => p !== 'Valentin');
			if (autres.length > 0) output += ` (avec ${autres.join(', ')})`;
		}
		output += '\n';
	}

	return output + '\n';
}

function formatEvenementsAVenir(evenements, cycleActuel) {
	if (!evenements?.length) return '';

	let output = '=== À VENIR ===\n';

	for (const evt of evenements) {
		const dans = evt.cycle - cycleActuel;
		const quand = dans === 0 ? 'Aujourd\'hui' : (dans === 1 ? 'Demain' : `Cycle ${evt.cycle}`);
		output += `• [${quand}`;
		if (evt.heure) output += ` ${evt.heure}`;
		output += `] ${evt.titre}`;
		if (evt.lieu_nom) output += ` @ ${evt.lieu_nom}`;
		output += '\n';
	}

	return output + '\n';
}

// ============================================================================
// FORMATAGE — RELATIONS VALENTIN
// ============================================================================

function formatRelationsValentin(relations, pnjPresentsNoms) {
	// Filtrer les PNJ déjà présents (ils ont leur fiche complète)
	const relationsAutres = relations.filter(r =>
		!pnjPresentsNoms.some(nom =>
			r.cible_nom.toLowerCase() === nom.toLowerCase()
		)
	);

	if (relationsAutres.length === 0) return '';

	let output = '=== RELATIONS ===\n';

	// Trier par niveau décroissant
	const triees = relationsAutres.sort((a, b) => {
		const niveauA = a.proprietes?.niveau ?? 0;
		const niveauB = b.proprietes?.niveau ?? 0;
		return niveauB - niveauA;
	});

	for (const rel of triees.slice(0, CONFIG.MAX_PERSONNAGES_FICHES)) {
		const niveau = rel.proprietes?.niveau ?? 0;
		output += `• ${rel.cible_nom} — ${niveau}/10`;
		if (rel.proprietes?.contexte) output += ` (${rel.proprietes.contexte})`;
		output += '\n';
	}

	return output + '\n';
}

// ============================================================================
// FORMATAGE — SCÈNES
// ============================================================================

function formatResumesScenes(scenes) {
	if (!scenes?.length) return '';

	let output = '=== SCÈNES DU CYCLE ===\n';

	for (const s of scenes) {
		output += `[${s.numero}. ${s.lieu}`;
		if (s.heure_debut) output += ` ${s.heure_debut}`;
		if (s.heure_fin) output += `-${s.heure_fin}`;
		output += `] ${s.resume || 'Pas de résumé'}\n`;
	}

	return output + '\n';
}

function formatMessagesScene(messages) {
	if (!messages?.length) return '';

	let output = '=== SCÈNE EN COURS ===\n';
	output += '(Maintiens une cohérence ABSOLUE avec ces échanges)\n\n';

	for (const m of messages) {
		const role = m.role === 'user' ? 'JOUEUR' : 'MJ';
		output += `${role}: ${m.content}\n\n`;
	}

	return output;
}

// ============================================================================
// FORMATAGE — ARCS NARRATIFS
// ============================================================================

async function formatArcs(supabase, partieId) {
	const arcs = await getEntitesParType(supabase, partieId, 'arc_narratif');

	const arcsActifs = arcs.filter(a => {
		const etat = a.proprietes?.etat || 'actif';
		return etat === 'actif';
	});

	if (arcsActifs.length === 0) return '';

	let output = '=== ARCS NARRATIFS ===\n';

	for (const arc of arcsActifs) {
		const props = arc.proprietes || {};
		const progression = props.progression || 0;
		output += `• ${arc.nom} (${props.type_arc || 'général'}) — ${progression}%\n`;
	}

	return output + '\n';
}

// ============================================================================
// DÉTECTION PNJ MENTIONNÉS DANS LE MESSAGE
// ============================================================================

async function getPnjMentionnes(supabase, partieId, userMessage, relationsValentin, pnjsPresentsNoms) {
	const messageLower = userMessage.toLowerCase();
	const pnjsMentionnes = [];

	for (const rel of relationsValentin) {
		const nom = rel.cible_nom;

		// Déjà présent → skip (il a déjà sa fiche complète)
		if (pnjsPresentsNoms.some(p => p.toLowerCase() === nom.toLowerCase())) {
			continue;
		}

		// Vérifier si le nom (ou prénom) est mentionné
		const nomLower = nom.toLowerCase();
		const prenomLower = nom.split(' ')[0].toLowerCase();

		if (messageLower.includes(nomLower) || messageLower.includes(prenomLower)) {
			const entiteId = await trouverEntite(supabase, partieId, nom, 'personnage');
			if (entiteId) {
				const [personnage, etats] = await Promise.all([
					getEntite(supabase, entiteId),
					getEtatsEntite(supabase, entiteId)
				]);
				if (personnage) {
					pnjsMentionnes.push({ personnage, relation: rel, etats });
				}
			}
		}
	}

	return pnjsMentionnes;
}

// ============================================================================
// CONSTRUCTION PRINCIPALE
// ============================================================================

/**
 * Construit le contexte complet pour Claude Sonnet
 */
export async function buildContext(supabase, partieId, gameState, userMessage) {
	const cycle = gameState?.partie?.cycle_actuel || 1;
	const lieuActuelNom = gameState?.partie?.lieu_actuel || '';
	const pnjsPresentsNoms = gameState?.partie?.pnjs_presents || [];

	// =========================================================================
	// REQUÊTES PARALLÈLES
	// =========================================================================

	const [
		protagoniste,
		ia,
		stats,
		inventaire,
		relationsValentin,
		sceneEnCours,
		scenesAnalysees,
		evenementsAVenir,
		cycleResumes
	] = await Promise.all([
		getProtagoniste(supabase, partieId),
		getIA(supabase, partieId),
		getStatsValentin(supabase, partieId),
		getInventaire(supabase, partieId),
		getRelationsValentin(supabase, partieId),
		getSceneEnCours(supabase, partieId),
		getScenesAnalyseesCycle(supabase, partieId, cycle),
		getEvenementsAVenir(supabase, partieId, cycle, CONFIG.MAX_EVENEMENTS_A_VENIR),
		supabase.from('cycle_resumes')
			.select('cycle, jour, resume')
			.eq('partie_id', partieId)
			.order('cycle', { ascending: false })
			.limit(CONFIG.CYCLES_RECENTS)
			.then(r => r.data || [])
	]);

	// Lieu actuel avec hiérarchie
	let lieuActuel = null;
	let hierarchieLieu = null;
	let pnjsFrequentsLieu = [];

	if (lieuActuelNom) {
		hierarchieLieu = await getLieuAvecHierarchie(supabase, partieId, lieuActuelNom);
		if (hierarchieLieu) {
			lieuActuel = hierarchieLieu;
			// Récupérer les PNJ fréquents du lieu ici
			if (hierarchieLieu.id) {
				pnjsFrequentsLieu = await getPnjsFrequentsLieu(supabase, partieId, hierarchieLieu.id);
			}
		}
	}

	// Messages de la scène en cours
	let messagesScene = [];
	if (sceneEnCours?.id) {
		messagesScene = await getMessagesScene(
			supabase,
			sceneEnCours.id,
			sceneEnCours.dernier_message_resume_id
		);
		// Limiter le nombre de messages
		if (messagesScene.length > CONFIG.MAX_MESSAGES_SCENE) {
			messagesScene = messagesScene.slice(-CONFIG.MAX_MESSAGES_SCENE);
		}
	}

	// =========================================================================
	// PNJ PRÉSENTS — FICHES COMPLÈTES
	// =========================================================================

	const pnjsPresentsData = [];
	for (const nom of pnjsPresentsNoms) {
		const entiteId = await trouverEntite(supabase, partieId, nom, 'personnage');
		if (!entiteId) continue;

		const [personnage, etats, arcs] = await Promise.all([
			getEntite(supabase, entiteId),
			getEtatsEntite(supabase, entiteId),
			getArcsPnj(supabase, partieId, entiteId) // Récupérer les arcs ici
		]);

		if (!personnage) continue;

		// Trouver la relation avec Valentin
		const relation = relationsValentin.find(r =>
			r.cible_nom.toLowerCase() === personnage.nom.toLowerCase()
		);

		pnjsPresentsData.push({ personnage, relation, etats, arcs });
	}

	// =========================================================================
	// ÉVÉNEMENTS RÉCENTS (liés au contexte)
	// =========================================================================

	let evenementsRecents = [];

	// Événements du cycle actuel et précédent
	const [evtCycleActuel, evtCyclePrecedent] = await Promise.all([
		getEvenementsCycle(supabase, partieId, cycle),
		cycle > 1 ? getEvenementsCycle(supabase, partieId, cycle - 1) : []
	]);

	evenementsRecents = [...evtCycleActuel, ...evtCyclePrecedent]
		.slice(0, CONFIG.MAX_EVENEMENTS_RECENTS);

	// =========================================================================
	// CONSTRUCTION DU CONTEXTE
	// =========================================================================

	let context = '';

	// 1. Situation actuelle (avec PNJ fréquents passés en paramètre)
	context += formatSituation(gameState?.partie, lieuActuel, hierarchieLieu, pnjsFrequentsLieu);

	// 2. Résumés cycles précédents
	if (cycleResumes.length > 0) {
		context += '=== CYCLES PRÉCÉDENTS ===\n';
		for (const r of [...cycleResumes].reverse()) {
			context += `[Cycle ${r.cycle}${r.jour ? ', ' + r.jour : ''}] ${r.resume}\n`;
		}
		context += '\n';
	}

	// 3. Scènes du cycle (terminées)
	context += formatResumesScenes(scenesAnalysees);

	// 4. Valentin
	context += formatValentin(protagoniste, ia, stats, inventaire);

	// 5. PNJ présents (fiches complètes, avec arcs passés en paramètre)
	if (pnjsPresentsData.length > 0) {
		context += '=== PNJ PRÉSENTS ===\n';
		for (const { personnage, relation, etats, arcs } of pnjsPresentsData) {
			context += formatPnjPresent(personnage, relation, etats, arcs) + '\n';
		}
	} else if (pnjsPresentsNoms.length === 0) {
		context += '=== PNJ PRÉSENTS ===\nValentin est seul.\n\n';
	}

	// 5bis. PNJ mentionnés dans le message (fiches complètes)
	const pnjsMentionnes = await getPnjMentionnes(
		supabase,
		partieId,
		userMessage,
		relationsValentin,
		pnjsPresentsNoms
	);

	if (pnjsMentionnes.length > 0) {
		context += '=== PNJ RÉFÉRENCÉS ===\n';
		for (const { personnage, relation, etats } of pnjsMentionnes) {
			context += formatPnjPresent(personnage, relation, etats) + '\n';
		}
	}

	// 6. Relations Valentin (autres PNJ connus)
	context += formatRelationsValentin(relationsValentin, pnjsPresentsNoms);

	// 7. Événements récents
	context += formatEvenementsRecents(evenementsRecents);

	// 8. Événements à venir
	context += formatEvenementsAVenir(evenementsAVenir, cycle);

	// 9. Arcs narratifs
	context += await formatArcs(supabase, partieId);

	// 10. Messages scène en cours
	context += formatMessagesScene(messagesScene);

	// 11. Action du joueur
	context += '=== ACTION ===\n';
	context += userMessage;

	// =========================================================================
	// RETOUR
	// =========================================================================

	return {
		context,
		sceneEnCours,
		protagoniste,
		stats,
		inventaire,
		relationsValentin
	};
}

// ============================================================================
// CONTEXTE INIT (nouvelle partie)
// ============================================================================

export function buildContextInit() {
	return 'Nouvelle partie. Lance le jeu. Génère le monde, les personnages, et la scène d\'arrivée.';
}

// ============================================================================
// CONTEXTE MINIMAL (pour régénération rapide)
// ============================================================================

export async function buildContextMinimal(supabase, partieId, gameState, userMessage) {
	const [protagoniste, stats, sceneEnCours] = await Promise.all([
		getProtagoniste(supabase, partieId),
		getStatsValentin(supabase, partieId),
		getSceneEnCours(supabase, partieId)
	]);

	let messagesScene = [];
	if (sceneEnCours?.id) {
		messagesScene = await getMessagesScene(supabase, sceneEnCours.id);
		messagesScene = messagesScene.slice(-10); // Derniers 10 messages seulement
	}

	let context = '=== SITUATION ===\n';
	context += `Cycle ${gameState?.partie?.cycle_actuel || 1}\n`;
	if (gameState?.partie?.lieu_actuel) {
		context += `Lieu: ${gameState.partie.lieu_actuel}\n`;
	}
	context += `Valentin: É${stats.energie} M${stats.moral} S${stats.sante} | ${stats.credits} cr\n\n`;

	context += formatMessagesScene(messagesScene);
	context += '=== ACTION ===\n' + userMessage;

	return { context, sceneEnCours, protagoniste, stats };
}

// ============================================================================
// EXPORTS UTILITAIRES
// ============================================================================

export {
	formatSituation,
	formatValentin,
	formatPnjPresent,
	formatPnjConnu,
	formatRelationsValentin,
	formatEvenementsRecents,
	formatEvenementsAVenir,
	formatResumesScenes,
	formatMessagesScene,
	CONFIG
};
