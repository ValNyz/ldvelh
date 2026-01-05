/**
 * Context Builder pour LDVELH
 * Construit le contexte pour Claude Sonnet depuis le KG
 */

import {
	getProtagoniste,
	getIA,
	getEntite,
	getLieuAvecHierarchie,
	getRelationsValentin,
	getInventaire,
	getStatsValentin,
	getEtatsEntite,
	getEvenementsAVenir,
	getEvenementsCycle,
	trouverEntite,
	getEntitesParType,
	getArcsPnj,
	getPnjsFrequentsLieu
} from '../kg/kgService.js';
import {
	getSceneEnCours,
	getMessagesScene,
	getScenesAnalyseesCycle
} from '../scene/sceneService.js';

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
// FORMATAGE
// ============================================================================

function formatSituation(partie, lieu, hierarchieLieu, pnjsFrequents = []) {
	let output = '=== SITUATION ===\n';

	if (partie?.jour || partie?.date_jeu) {
		output += `${partie.jour || ''} ${partie.date_jeu || ''}\n`;
	}
	if (partie?.heure) {
		output += `Heure: ${partie.heure}\n`;
	}

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

	if (pnjsFrequents.length > 0) {
		output += 'PNJ fréquents: ';
		output += pnjsFrequents.map(f => {
			let str = f.nom;
			if (f.periode && f.periode !== 'aléatoire') str += ` (${f.periode})`;
			return str;
		}).join(', ');
		output += '\n';
	}

	return output + '\n';
}

function formatValentin(protagoniste, ia, stats, inventaire) {
	let output = '=== VALENTIN ===\n';

	output += `Énergie: ${stats.energie}/5 | Moral: ${stats.moral}/5 | Santé: ${stats.sante}/5\n`;
	output += `Crédits: ${stats.credits}\n`;

	if (inventaire?.length > 0) {
		const items = inventaire.map(i => {
			if (i.quantite > 1) return `${i.objet_nom} (x${i.quantite})`;
			return i.objet_nom;
		});
		output += `Inventaire: ${items.join(', ')}\n`;
	}

	const comp = protagoniste?.proprietes?.competences || {};
	const compCles = ['informatique', 'social', 'cuisine', 'observation', 'empathie'];
	const compStr = compCles
		.filter(c => comp[c] !== undefined)
		.map(c => `${c.slice(0, 3).toUpperCase()} ${comp[c]}`)
		.join(', ');
	if (compStr) output += `Compétences: ${compStr}\n`;

	if (protagoniste?.proprietes?.poste) {
		output += `Poste: ${protagoniste.proprietes.poste}\n`;
	}

	if (ia?.nom) {
		output += `IA: ${ia.nom}`;
		if (ia.proprietes?.traits?.length > 0) {
			output += ` (${ia.proprietes.traits.join(', ')})`;
		}
		output += '\n';
	}

	return output + '\n';
}

function formatPnjPresent(personnage, relation, etats, arcs = []) {
	const props = personnage.proprietes || {};
	const relProps = relation?.proprietes || {};
	const niveau = relProps.niveau ?? 0;
	const disposition = etats.disposition?.valeur || 'neutre';

	let fiche = `## ${personnage.nom.toUpperCase()} (rel: ${niveau}/10, ${disposition})\n`;

	const infos = [];
	if (props.sexe) infos.push(props.sexe === 'F' ? '♀' : (props.sexe === 'M' ? '♂' : '⚬'));
	if (props.age) infos.push(`${props.age} ans`);
	if (props.espece && props.espece !== 'humain') infos.push(props.espece);
	if (props.metier) infos.push(props.metier);
	if (infos.length > 0) fiche += `${infos.join(', ')}\n`;

	if (props.physique) fiche += `Physique: ${props.physique}\n`;
	if (props.traits?.length > 0) fiche += `Traits: ${props.traits.join(', ')}\n`;

	const statSocial = etats.stat_social?.valeur || '3';
	const statTravail = etats.stat_travail?.valeur || '3';
	fiche += `Stats: Social ${statSocial}/5, Travail ${statTravail}/5\n`;

	if (props.interet_romantique && relProps.etape_romantique !== undefined) {
		const etapes = ['Inconnus', 'Indifférence', 'Reconnaissance', 'Sympathie', 'Curiosité', 'Intérêt', 'Attirance'];
		fiche += `Romance: ${relProps.etape_romantique}/6 (${etapes[relProps.etape_romantique] || '?'})\n`;
	}

	if (arcs.length > 0) {
		const arcsStr = arcs.filter(a => a.etat === 'actif').map(a => `${a.nom} (${a.progression}%)`).join(', ');
		if (arcsStr) fiche += `Arcs: ${arcsStr}\n`;
	}

	return fiche;
}

function formatRelationsValentin(relations, pnjPresentsNoms) {
	const relationsAutres = relations.filter(r =>
		!pnjPresentsNoms.some(nom => r.cible_nom.toLowerCase() === nom.toLowerCase())
	);

	if (relationsAutres.length === 0) return '';

	let output = '=== RELATIONS ===\n';

	const triees = relationsAutres.sort((a, b) => {
		return (b.proprietes?.niveau ?? 0) - (a.proprietes?.niveau ?? 0);
	});

	for (const rel of triees.slice(0, CONFIG.MAX_PERSONNAGES_FICHES)) {
		const niveau = rel.proprietes?.niveau ?? 0;
		output += `• ${rel.cible_nom} — ${niveau}/10`;
		if (rel.proprietes?.contexte) output += ` (${rel.proprietes.contexte})`;
		output += '\n';
	}

	return output + '\n';
}

function formatEvenementsRecents(evenements) {
	if (!evenements?.length) return '';

	let output = '=== ÉVÉNEMENTS RÉCENTS ===\n';

	for (const evt of evenements) {
		output += `• [Cycle ${evt.cycle}${evt.heure ? ' ' + evt.heure : ''}] ${evt.titre}`;
		const autres = (evt.participants || []).filter(p => p !== 'Valentin');
		if (autres.length > 0) output += ` (avec ${autres.join(', ')})`;
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
		output += `• [${quand}${evt.heure ? ' ' + evt.heure : ''}] ${evt.titre}`;
		if (evt.lieu_nom) output += ` @ ${evt.lieu_nom}`;
		output += '\n';
	}

	return output + '\n';
}

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
	output += '(Cohérence ABSOLUE avec ces échanges)\n\n';

	for (const m of messages) {
		const role = m.role === 'user' ? 'JOUEUR' : 'MJ';
		output += `${role}: ${m.content}\n\n`;
	}

	return output;
}

async function formatArcs(supabase, partieId) {
	const arcs = await getEntitesParType(supabase, partieId, 'arc_narratif');

	const arcsActifs = arcs.filter(a => (a.proprietes?.etat || 'actif') === 'actif');

	if (arcsActifs.length === 0) return '';

	let output = '=== ARCS NARRATIFS ===\n';

	for (const arc of arcsActifs) {
		const props = arc.proprietes || {};
		output += `• ${arc.nom} (${props.type_arc || 'général'}) — ${props.progression || 0}%\n`;
	}

	return output + '\n';
}

// ============================================================================
// DÉTECTION PNJ MENTIONNÉS
// ============================================================================

async function getPnjMentionnes(supabase, partieId, userMessage, relationsValentin, pnjsPresentsNoms) {
	const messageLower = userMessage.toLowerCase();

	// Filtrer les candidats (synchrone)
	const candidats = relationsValentin.filter(rel => {
		const nom = rel.cible_nom;
		if (pnjsPresentsNoms.some(p => p.toLowerCase() === nom.toLowerCase())) {
			return false;
		}
		const nomLower = nom.toLowerCase();
		const prenomLower = nom.split(' ')[0].toLowerCase();
		return messageLower.includes(nomLower) || messageLower.includes(prenomLower);
	});

	// Charger les données en parallèle
	const pnjsMentionnes = await Promise.all(
		candidats.map(async (rel) => {
			const entiteId = await trouverEntite(supabase, partieId, rel.cible_nom, 'personnage');
			if (!entiteId) return null;

			const [personnage, etats] = await Promise.all([
				getEntite(supabase, entiteId),
				getEtatsEntite(supabase, entiteId)
			]);

			if (!personnage) return null;
			return { personnage, relation: rel, etats };
		})
	);

	return pnjsMentionnes.filter(Boolean);
}

// ============================================================================
// CONSTRUCTION PRINCIPALE
// ============================================================================

export async function buildContext(supabase, partieId, gameState, userMessage) {
	const cycle = gameState?.partie?.cycle_actuel || 1;
	const lieuActuelNom = gameState?.partie?.lieu_actuel || '';
	const pnjsPresentsNoms = gameState?.partie?.pnjs_presents || [];

	// Requêtes parallèles (1er batch)
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

	// Lieu avec hiérarchie et PNJ fréquents
	let lieuActuel = null;
	let hierarchieLieu = null;
	let pnjsFrequentsLieu = [];

	if (lieuActuelNom) {
		hierarchieLieu = await getLieuAvecHierarchie(supabase, partieId, lieuActuelNom);
		if (hierarchieLieu) {
			lieuActuel = hierarchieLieu;
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
		if (messagesScene.length > CONFIG.MAX_MESSAGES_SCENE) {
			messagesScene = messagesScene.slice(-CONFIG.MAX_MESSAGES_SCENE);
		}
	}

	// PNJ présents (parallèle)
	const pnjsPresentsData = await Promise.all(
		pnjsPresentsNoms.map(async (nom) => {
			const entiteId = await trouverEntite(supabase, partieId, nom, 'personnage');
			if (!entiteId) return null;

			const [personnage, etats, arcs] = await Promise.all([
				getEntite(supabase, entiteId),
				getEtatsEntite(supabase, entiteId),
				getArcsPnj(supabase, partieId, entiteId)
			]);

			if (!personnage) return null;

			const relation = relationsValentin.find(r =>
				r.cible_nom.toLowerCase() === personnage.nom.toLowerCase()
			);

			return { personnage, relation, etats, arcs };
		})
	).then(results => results.filter(Boolean));

	// Événements récents
	const [evtCycleActuel, evtCyclePrecedent] = await Promise.all([
		getEvenementsCycle(supabase, partieId, cycle),
		cycle > 1 ? getEvenementsCycle(supabase, partieId, cycle - 1) : Promise.resolve([])
	]);

	const evenementsRecents = [...evtCycleActuel, ...evtCyclePrecedent]
		.slice(0, CONFIG.MAX_EVENEMENTS_RECENTS);

	// === CONSTRUCTION DU CONTEXTE ===

	let context = '';

	// 1. Situation
	context += formatSituation(gameState?.partie, lieuActuel, hierarchieLieu, pnjsFrequentsLieu);

	// 2. Cycles précédents
	if (cycleResumes.length > 0) {
		context += '=== CYCLES PRÉCÉDENTS ===\n';
		for (const r of [...cycleResumes].reverse()) {
			context += `[Cycle ${r.cycle}${r.jour ? ', ' + r.jour : ''}] ${r.resume}\n`;
		}
		context += '\n';
	}

	// 3. Scènes
	context += formatResumesScenes(scenesAnalysees);

	// 4. Valentin
	context += formatValentin(protagoniste, ia, stats, inventaire);

	// 5. PNJ présents
	if (pnjsPresentsData.length > 0) {
		context += '=== PNJ PRÉSENTS ===\n';
		for (const { personnage, relation, etats, arcs } of pnjsPresentsData) {
			context += formatPnjPresent(personnage, relation, etats, arcs) + '\n';
		}
	} else if (pnjsPresentsNoms.length === 0) {
		context += '=== PNJ PRÉSENTS ===\nValentin est seul.\n\n';
	}

	// 6. PNJ mentionnés
	const pnjsMentionnes = await getPnjMentionnes(
		supabase, partieId, userMessage, relationsValentin, pnjsPresentsNoms
	);

	if (pnjsMentionnes.length > 0) {
		context += '=== PNJ RÉFÉRENCÉS ===\n';
		for (const { personnage, relation, etats } of pnjsMentionnes) {
			context += formatPnjPresent(personnage, relation, etats) + '\n';
		}
	}

	// 7. Relations
	context += formatRelationsValentin(relationsValentin, pnjsPresentsNoms);

	// 8. Événements récents
	context += formatEvenementsRecents(evenementsRecents);

	// 9. À venir
	context += formatEvenementsAVenir(evenementsAVenir, cycle);

	// 10. Arcs
	context += await formatArcs(supabase, partieId);

	// 11. Messages scène
	context += formatMessagesScene(messagesScene);

	// 12. Action
	context += '=== ACTION ===\n';
	context += userMessage;

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
// CONTEXTE INIT
// ============================================================================

export function buildContextInit() {
	return 'Nouvelle partie. Lance le jeu. Génère le monde, les personnages, et la scène d\'arrivée.';
}

// ============================================================================
// EXPORTS
// ============================================================================

export { CONFIG };
