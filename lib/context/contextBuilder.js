/**
 * Context Builder pour LDVELH
 * Version simplifiée sans scènes
 */

import { CONTEXT_CONFIG, LABELS_LOCALISATION } from '../constants.js';
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

// ============================================================================
// NOUVELLES FONCTIONS: Récupération messages et résumés
// ============================================================================

/**
 * Récupère les résumés des messages du cycle en cours
 */
async function getResumesCycle(supabase, partieId, cycle, excludeLast = 5) {
	const { data, error } = await supabase
		.from('chat_messages')
		.select('resume, created_at')
		.eq('partie_id', partieId)
		.eq('cycle', cycle)
		.eq('role', 'assistant')
		.not('resume', 'is', null)
		.order('created_at', { ascending: true });

	if (error) {
		console.error('[Context] Erreur getResumesCycle:', error);
		return [];
	}

	if (!data?.length) return [];

	// Exclure les N derniers pour éviter redondance avec les messages récents
	const cutoff = Math.max(0, data.length - excludeLast);
	return data.slice(0, cutoff);
}

/**
 * Récupère les N derniers messages de la conversation avec contexte
 */
async function getDerniersMessages(supabase, partieId, limit = 5) {
	const { data, error } = await supabase
		.from('chat_messages')
		.select('role, content, lieu, pnjs_presents, created_at')
		.eq('partie_id', partieId)
		.order('created_at', { ascending: false })
		.limit(limit * 2); // x2 car user+assistant par échange

	if (error) {
		console.error('[Context] Erreur getDerniersMessages:', error);
		return [];
	}

	// Inverser pour avoir l'ordre chronologique
	return (data || []).reverse();
}

// ============================================================================
// FORMATAGE
// ============================================================================

function formatInventaireEnrichi(inventaire, nomAppartement = 'Appartement') {
	if (!inventaire?.length) return '\nInventaire: (vide)\n';

	const parLocalisation = {};

	for (const item of inventaire) {
		let loc = item.localisation || item.relation_props?.localisation || 'sur_soi';
		if (loc.toLowerCase().includes('appartement') || loc === 'chez_soi') {
			loc = 'appartement';
		}
		if (!parLocalisation[loc]) parLocalisation[loc] = [];
		parLocalisation[loc].push(item);
	}

	let output = '\nInventaire:\n';
	const ordreLocalisations = ['sur_soi', 'sac_a_dos', 'sac', 'valise', 'appartement', 'bureau', 'stockage', 'prete'];

	const localisationsTri = Object.keys(parLocalisation).sort((a, b) => {
		const idxA = ordreLocalisations.indexOf(a);
		const idxB = ordreLocalisations.indexOf(b);
		if (idxA === -1 && idxB === -1) return a.localeCompare(b);
		if (idxA === -1) return 1;
		if (idxB === -1) return -1;
		return idxA - idxB;
	});

	for (const loc of localisationsTri) {
		const items = parLocalisation[loc];
		let label = LABELS_LOCALISATION[loc];
		if (!label) label = `📌 ${loc}`;
		if (loc === 'appartement' && nomAppartement !== 'Appartement') {
			label = `🏠 ${nomAppartement}`;
		}

		output += `  ${label}:\n`;

		const parCategorie = {};
		for (const item of items) {
			const cat = item.categorie || item.objet_props?.categorie || 'autre';
			if (!parCategorie[cat]) parCategorie[cat] = [];
			parCategorie[cat].push(item);
		}

		for (const cat of Object.keys(parCategorie).sort()) {
			for (const item of parCategorie[cat]) {
				let ligne = `    • ${item.objet_nom}`;
				const qte = item.quantite || 1;
				if (qte > 1) ligne += ` (x${qte})`;
				const etat = item.etat || item.objet_props?.etat;
				if (etat && !['neuf', 'bon'].includes(etat)) {
					const etatsEmoji = { 'use': '⚠️', 'endommage': '🔧', 'casse': '❌' };
					ligne += ` [${etatsEmoji[etat] || ''}${etat}]`;
				}
				const preteA = item.prete_a || item.relation_props?.prete_a;
				if (preteA) ligne += ` → prêté à ${preteA}`;
				output += ligne + '\n';
			}
		}
	}

	const valeurTotale = inventaire.reduce((sum, item) => {
		const valeur = item.valeur_neuve || item.objet_props?.valeur_neuve || 0;
		const qte = item.quantite || 1;
		return sum + (valeur * qte);
	}, 0);

	if (valeurTotale > 0) {
		output += `  💰 Valeur totale estimée: ~${valeurTotale} cr\n`;
	}

	return output;
}

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

function formatValentin(protagoniste, ia, stats, inventaire, nomAppartement) {
	let output = '=== VALENTIN ===\n';
	output += `Énergie: ${stats.energie}/5 | Moral: ${stats.moral}/5 | Santé: ${stats.sante}/5\n`;
	output += `Crédits: ${stats.credits}\n`;
	output += formatInventaireEnrichi(inventaire, nomAppartement);

	const comp = protagoniste?.proprietes?.competences || {};
	const compCles = ['informatique', 'social', 'cuisine', 'observation', 'empathie'];
	const compStr = compCles
		.filter(c => comp[c] !== undefined)
		.map(c => `${c.slice(0, 3).toUpperCase()} ${comp[c]}`)
		.join(', ');
	if (compStr) output += `\nCompétences: ${compStr}\n`;

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

	for (const rel of triees.slice(0, CONTEXT_CONFIG.MAX_PERSONNAGES_FICHES)) {
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

function formatEvenementsAVenir(evenements, cycleActuel, heureActuelle = null) {
	if (!evenements?.length) return '';

	const aujourdhui = evenements.filter(e => e.cycle === cycleActuel);
	const plusTard = evenements.filter(e => e.cycle > cycleActuel);

	let output = '=== À VENIR ===\n';

	if (aujourdhui.length > 0) {
		output += '⚠️ ÉVÉNEMENTS AUJOURD\'HUI — VÉRIFIER AVANT DE RÉPONDRE\n\n';
	}

	for (const evt of aujourdhui) {
		let urgence = '📅 Aujourd\'hui';

		if (heureActuelle && evt.heure) {
			const heureEvt = parseHeure(evt.heure);
			const heureNow = parseHeure(heureActuelle);

			if (heureEvt !== null && heureNow !== null) {
				const diffMinutes = heureEvt - heureNow;

				if (diffMinutes < 0) {
					urgence = '⏰ PASSÉ (vérifier si honoré)';
				} else if (diffMinutes <= 30) {
					urgence = '🔴 IMMINENT';
				} else if (diffMinutes <= 120) {
					urgence = '🟠 Dans moins de 2h';
				}
			}
		}

		output += `• [${urgence}${evt.heure ? ' ' + evt.heure : ''}] ${evt.titre}`;
		if (evt.lieu_nom) output += ` @ ${evt.lieu_nom}`;
		if (evt.participants?.length > 0) {
			const autres = evt.participants.filter(p => p.toLowerCase() !== 'valentin');
			if (autres.length > 0) output += ` (avec ${autres.join(', ')})`;
		}
		output += '\n';
	}

	if (aujourdhui.length > 0 && plusTard.length > 0) {
		output += '\n';
	}

	for (const evt of plusTard) {
		const dans = evt.cycle - cycleActuel;
		const quand = dans === 1 ? 'Demain' : `Dans ${dans} jours`;

		output += `• [${quand}${evt.heure ? ' ' + evt.heure : ''}] ${evt.titre}`;
		if (evt.lieu_nom) output += ` @ ${evt.lieu_nom}`;
		if (evt.participants?.length > 0) {
			const autres = evt.participants.filter(p => p.toLowerCase() !== 'valentin');
			if (autres.length > 0) output += ` (avec ${autres.join(', ')})`;
		}
		output += '\n';
	}

	return output + '\n';
}

function parseHeure(heureStr) {
	if (!heureStr) return null;
	const match = heureStr.match(/(\d{1,2})[h:]?(\d{2})?/);
	if (!match) return null;
	const heures = parseInt(match[1]);
	const minutes = parseInt(match[2] || '0');
	return heures * 60 + minutes;
}

// NOUVEAU: Formatage des résumés du cycle
function formatResumesCycle(resumes) {
	if (!resumes?.length) return '';

	let output = '=== RÉSUMÉS DU CYCLE ===\n';
	output += '(Ce qui s\'est passé aujourd\'hui)\n\n';

	for (let i = 0; i < resumes.length; i++) {
		output += `${i + 1}. ${resumes[i].resume}\n`;
	}

	return output + '\n';
}

// Formatage des derniers messages avec contexte lieu/PNJ
function formatDerniersMessages(messages) {
	if (!messages?.length) return '';

	let output = '=== CONVERSATION RÉCENTE ===\n';
	output += '(Cohérence ABSOLUE avec ces échanges)\n\n';

	let dernierLieu = null;

	for (const m of messages) {
		// Afficher le changement de lieu si pertinent
		if (m.lieu && m.lieu !== dernierLieu) {
			output += `--- ${m.lieu}`;
			if (m.pnjs_presents?.length > 0) {
				output += ` (avec ${m.pnjs_presents.join(', ')})`;
			}
			output += ' ---\n';
			dernierLieu = m.lieu;
		}

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

	const candidats = relationsValentin.filter(rel => {
		const nom = rel.cible_nom;
		if (pnjsPresentsNoms.some(p => p.toLowerCase() === nom.toLowerCase())) {
			return false;
		}
		const nomLower = nom.toLowerCase();
		const prenomLower = nom.split(' ')[0].toLowerCase();
		return messageLower.includes(nomLower) || messageLower.includes(prenomLower);
	});

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
// TROUVER NOM APPARTEMENT
// ============================================================================

async function trouverNomAppartement(supabase, partieId) {
	const protagoniste = await getProtagoniste(supabase, partieId);
	if (!protagoniste) return 'Appartement';

	const { data: relHabite } = await supabase
		.from('kg_relations')
		.select(`cible_id, kg_entites!kg_relations_cible_id_fkey(nom, proprietes)`)
		.eq('source_id', protagoniste.id)
		.eq('type_relation', 'habite')
		.is('cycle_fin', null)
		.single();

	if (relHabite?.kg_entites?.nom) {
		return relHabite.kg_entites.nom;
	}

	const lieux = await getEntitesParType(supabase, partieId, 'lieu');
	const appart = lieux.find(l =>
		l.nom.toLowerCase().includes('appartement') ||
		l.proprietes?.type_lieu === 'habitat'
	);

	return appart?.nom || 'Appartement';
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
		resumesCycle,
		derniersMessages,
		evenementsAVenir,
		cycleResumes,
		nomAppartement
	] = await Promise.all([
		getProtagoniste(supabase, partieId),
		getIA(supabase, partieId),
		getStatsValentin(supabase, partieId),
		getInventaire(supabase, partieId),
		getRelationsValentin(supabase, partieId),
		getResumesCycle(supabase, partieId, cycle),
		getDerniersMessages(supabase, partieId, CONTEXT_CONFIG.MAX_MESSAGES_RECENTS || 5),
		getEvenementsAVenir(supabase, partieId, cycle, CONTEXT_CONFIG.MAX_EVENEMENTS_A_VENIR),
		supabase.from('cycle_resumes')
			.select('cycle, jour, resume')
			.eq('partie_id', partieId)
			.order('cycle', { ascending: false })
			.limit(CONTEXT_CONFIG.CYCLES_RECENTS)
			.then(r => r.data || []),
		trouverNomAppartement(supabase, partieId)
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
		.slice(0, CONTEXT_CONFIG.MAX_EVENEMENTS_RECENTS);

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

	// 3. NOUVEAU: Résumés du cycle en cours
	context += formatResumesCycle(resumesCycle.map(r => ({ resume: r.resume })));

	// 4. Valentin
	context += formatValentin(protagoniste, ia, stats, inventaire, nomAppartement);

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
	context += formatEvenementsAVenir(evenementsAVenir, cycle, gameState?.partie?.heure);

	// 10. Arcs
	context += await formatArcs(supabase, partieId);

	// 11. NOUVEAU: Derniers messages (remplace la scène)
	context += formatDerniersMessages(derniersMessages);

	// 12. Action
	context += '=== ACTION ===\n';
	context += userMessage;

	return {
		context,
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
