/**
 * Context Builder pour LDVELH - Branche scenes
 * Gère la construction du contexte pour Claude avec le nouveau système de scènes
 */

import { calculerSolde, calculerInventaire, getTransactionsCycle } from './financeService.js';
import {
	getSceneEnCours,
	getScenesAnalyseesCycle,
	getMessagesScene,
	formaterResumesIntermediaires
} from './sceneService.js';
import { getFaitsPertinents, formaterFaitsPourContexte } from './faitsService.js';

const CYCLES_PNJ_RECENTS = 6;

// ============================================================================
// FORMATAGE
// ============================================================================

function formatSituationActuelle(partie, lieu) {
	let output = '=== SITUATION ACTUELLE ===\n';

	// Date et heure
	if (partie?.jour || partie?.date_jeu) {
		output += `Date: ${partie.jour || ''} ${partie.date_jeu || ''}\n`;
	}
	if (partie?.heure) {
		output += `Heure: ${partie.heure}\n`;
	}

	// Lieu
	if (lieu) {
		output += `Lieu: ${lieu.nom}`;
		if (lieu.type) output += ` (${lieu.type})`;
		if (lieu.secteur) output += ` — Secteur ${lieu.secteur}`;
		output += '\n';
		if (lieu.description) output += `${lieu.description}\n`;
	} else if (partie?.lieu_actuel) {
		output += `Lieu: ${partie.lieu_actuel}\n`;
	}

	// PNJ présents
	if (partie?.pnjs_presents?.length == 0) {
		output += `Valentin est seul.\n`;
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

function formatPnjPresent(pnj) {
	let fiche = `## ${pnj.nom.toUpperCase()} (rel: ${pnj.relation ?? 0}/10, ${pnj.disposition || 'neutre'})\n`;

	const infos = [];
	if (pnj.age) infos.push(`${pnj.age} ans`);
	if (pnj.espece && pnj.espece !== 'humain') infos.push(pnj.espece);
	if (pnj.metier) infos.push(pnj.metier);
	if (pnj.domicile) infos.push(`vit: ${pnj.domicile}`);
	if (infos.length) fiche += `- ${infos.join(', ')}\n`;

	if (pnj.physique) fiche += `- Physique: ${pnj.physique}\n`;
	if (pnj.traits?.length) fiche += `- Traits: ${pnj.traits.join(', ')}\n`;

	fiche += `- Stats: Social ${pnj.stat_social ?? 3}/5, Travail ${pnj.stat_travail ?? 3}/5, Santé ${pnj.stat_sante ?? 3}/5\n`;

	if (pnj.etape_romantique > 0) {
		const etapes = ['Inconnus', 'Indifférence', 'Reconnaissance', 'Sympathie', 'Curiosité', 'Intérêt', 'Attirance'];
		fiche += `- Étape romantique: ${pnj.etape_romantique}/6 (${etapes[pnj.etape_romantique] || '?'})\n`;
	}

	if (pnj.arc) fiche += `- Arc: "${pnj.arc}"\n`;

	return fiche;
}

function formatPnjMinimal(pnj) {
	let ligne = `• ${pnj.nom} - rel: ${pnj.relation ?? 0}/10`;
	if (pnj.disposition && pnj.disposition !== 'neutre') ligne += ` (${pnj.disposition})`;
	if (pnj.metier) ligne += ` - ${pnj.metier}`;
	if (pnj.dernier_contact) ligne += ` - vu cycle ${pnj.dernier_contact}`;
	return ligne;
}

function formatValentin(valentin, ia, credits, inventaire) {
	if (!valentin) return '';

	let output = '=== ÉTAT VALENTIN ===\n';
	output += `Énergie: ${valentin.energie ?? 3}/5 | Moral: ${valentin.moral ?? 3}/5 | Santé: ${valentin.sante ?? 5}/5\n`;
	output += `Crédits: ${credits ?? 1400}\n`;

	if (inventaire?.length) {
		output += `Inventaire: ${inventaire.join(', ')}\n`;
	}

	const c = valentin.competences || {};
	output += `Compétences: Info ${c.informatique ?? 5}, Sys ${c.systemes ?? 4}, `;
	output += `Soc ${c.social ?? 2}, Cui ${c.cuisine ?? 3}, Bri ${c.bricolage ?? 3}, Méd ${c.medical ?? 1}\n`;

	if (valentin.poste) output += `Poste: ${valentin.poste}\n`;
	if (ia?.nom) output += `IA: ${ia.nom} (sarcastique)\n`;

	return output + '\n';
}

function formatTransactions(transactions) {
	if (!transactions?.length) return '';

	let output = '=== TRANSACTIONS DU CYCLE ===\n';
	for (const tx of transactions) {
		const signe = tx.montant >= 0 ? '+' : '';
		output += `• [${tx.heure || '??h'}] ${signe}${tx.montant} cr`;
		if (tx.objet) output += ` (${tx.objet})`;
		if (tx.description) output += ` — ${tx.description}`;
		output += '\n';
	}
	output += 'NE PAS régénérer ces transactions.\n';
	return output + '\n';
}

function formatMessagesScene(messages, resumeIntermediaire) {
	if (!messages?.length && !resumeIntermediaire) return '';

	let output = '=== SCÈNE EN COURS ===\n';
	output += '(IMPORTANT: Maintiens une cohérence ABSOLUE avec ces échanges)\n\n';

	const resumeFormate = formaterResumesIntermediaires(resumeIntermediaire);
	if (resumeFormate) {
		output += `> Résumé précédent: ${resumeFormate}\n\n`;
	}

	for (const m of messages) {
		const role = m.role === 'user' ? 'VALENTIN' : 'MJ';
		output += `${role}: ${m.content}\n\n`;
	}

	return output;
}

function formatArcs(arcs) {
	if (!arcs?.length) return '';
	let output = '=== ARCS NARRATIFS ===\n';
	for (const arc of arcs) {
		if (arc.etat && arc.etat !== 'actif') continue;
		output += `- ${arc.nom || 'Arc'} | ${arc.type || 'général'} - ${arc.progression || 0}%\n`;
	}
	return output + '\n';
}

function formatAVenir(aVenir, cycleActuel) {
	if (!aVenir?.length) return '';

	const pertinents = aVenir.filter(ev =>
		!ev.realise && ev.cycle_prevu && ev.cycle_prevu <= cycleActuel + 3
	);

	if (!pertinents.length) return '';

	let output = '=== ÉVÉNEMENTS PLANIFIÉS ===\n';
	for (const ev of pertinents.slice(0, 5)) {
		output += `- [Cycle ${ev.cycle_prevu}] ${ev.evenement}`;
		if (ev.pnjs_impliques?.length) output += ` (avec: ${ev.pnjs_impliques.join(', ')})`;
		output += '\n';
	}
	return output + '\n';
}

// ============================================================================
// CONSTRUCTION PRINCIPALE
// ============================================================================

export async function buildContext(supabase, partieId, gameState, userMessage, options = {}) {
	const { faitsEnabled = true } = options;

	const cycle = gameState?.partie?.cycle_actuel || 1;
	const lieuActuelNom = gameState?.partie?.lieu_actuel || '';
	const pnjsPresents = gameState?.partie?.pnjs_presents || [];

	// Requêtes parallèles
	const [
		sceneEnCours,
		scenesAnalysees,
		resumesCycles,
		lieuActuel,
		pnjData,
		faits,
		credits,
		inventaire,
		transactions,
		arcsData,
		aVenirData
	] = await Promise.all([
		getSceneEnCours(supabase, partieId),
		getScenesAnalyseesCycle(supabase, partieId, cycle),
		supabase.from('cycle_resumes')
			.select('cycle, jour, date_jeu, resume')
			.eq('partie_id', partieId)
			.order('cycle', { ascending: false })
			.limit(3)
			.then(r => r.data || []),
		lieuActuelNom
			? supabase.from('lieux')
				.select('*')
				.eq('partie_id', partieId)
				.ilike('nom', lieuActuelNom)
				.maybeSingle()
				.then(r => r.data)
			: null,
		supabase.from('pnj')
			.select('*')
			.eq('partie_id', partieId)
			.then(r => r.data || []),
		faitsEnabled
			? getFaitsPertinents(supabase, partieId, {
				pnjPresents: pnjsPresents,
				lieuActuel: lieuActuelNom,
				cycleActuel: cycle
			})
			: [],
		calculerSolde(supabase, partieId),
		calculerInventaire(supabase, partieId),
		getTransactionsCycle(supabase, partieId, cycle),
		supabase.from('arcs')
			.select('*')
			.eq('partie_id', partieId)
			.eq('etat', 'actif')
			.then(r => r.data || []),
		supabase.from('a_venir')
			.select('*')
			.eq('partie_id', partieId)
			.eq('realise', false)
			.gte('cycle_prevu', cycle)
			.order('cycle_prevu', { ascending: true })
			.limit(5)
			.then(r => r.data || [])
	]);

	// Messages de la scène en cours
	let messagesScenePrecedente = [];
	let messagesScene = [];
	let resumeIntermediaire = null;


	if (sceneEnCours) {
		if (sceneEnCours.id > 0) {
			messagesScenePrecedente = await getMessagesScene(
				supabase,
				sceneEnCours.id - 1
			);
		}

		resumeIntermediaire = sceneEnCours.resume_intermediaire;
		messagesScene = await getMessagesScene(
			supabase,
			sceneEnCours.id,
			sceneEnCours.dernier_message_resume_id
		);
	}

	// Filtrer les PNJ
	const pnjPresentsData = pnjData.filter(p =>
		pnjsPresents.some(nom => p.nom.toLowerCase() === nom.toLowerCase())
	);

	// PNJ connus mais pas présents : récents OU relation > 0 OU initiaux/romantiques
	// Triés par : relation (desc) puis dernier_contact (desc)
	const pnjConnus = pnjData
		.filter(p =>
			!pnjsPresents.some(nom => p.nom.toLowerCase() === nom.toLowerCase()) &&
			((p.dernier_contact && p.dernier_contact >= cycle - CYCLES_PNJ_RECENTS) ||
				(p.relation && p.relation > 0) ||
				p.est_initial ||
				p.interet_romantique)
		)
		.sort((a, b) => {
			// D'abord par relation (plus haute en premier)
			const relDiff = (b.relation || 0) - (a.relation || 0);
			if (relDiff !== 0) return relDiff;
			// Puis par dernier contact (plus récent en premier)
			return (b.dernier_contact || 0) - (a.dernier_contact || 0);
		});

	// ============================================================================
	// CONSTRUCTION DU CONTEXTE
	// ============================================================================

	let context = '';

	// 1. SITUATION ACTUELLE (date, heure, lieu, PNJ présents)
	context += formatSituationActuelle(gameState?.partie, lieuActuel);

	// 2. Résumés cycles précédents
	if (resumesCycles.length) {
		context += '=== RÉSUMÉS CYCLES PRÉCÉDENTS ===\n';
		for (const r of [...resumesCycles].reverse()) {
			context += `[Cycle ${r.cycle}${r.jour ? ', ' + r.jour : ''}] ${r.resume}\n`;
		}
		context += '\n';
	}

	// 3. Scènes du cycle (terminées)
	context += formatResumesScenes(scenesAnalysees);

	// 4. Faits établis
	if (faits.length) {
		context += formaterFaitsPourContexte(faits);
	}

	// 5. PNJ présents (fiches complètes)
	if (pnjPresentsData.length) {
		context += '=== PNJ PRÉSENTS ===\n';
		for (const pnj of pnjPresentsData) {
			context += formatPnjPresent(pnj) + '\n';
		}
	}

	// 6. PNJ connus (fiches minimales) - seulement si pertinent
	if (pnjConnus.length) {
		context += '=== AUTRES PNJ CONNUS ===\n';
		for (const pnj of pnjConnus.slice(0, 10)) { // Limiter à 10
			context += formatPnjMinimal(pnj) + '\n';
		}
		context += '\n';
	}

	// 7. État Valentin
	context += formatValentin(gameState?.valentin, gameState?.ia, credits, inventaire);

	// 8. Transactions du cycle
	context += formatTransactions(transactions);

	// 9. Arcs narratifs
	context += formatArcs(arcsData);

	// 10. Événements à venir
	context += formatAVenir(aVenirData, cycle);

	// 11. Messages scène en cours
	context += formatMessagesScene(messagesScenePrecedente);
	context += formatMessagesScene(messagesScene, resumeIntermediaire);

	// 12. Action du joueur
	context += '=== ACTION ===\n';
	context += userMessage;

	return {
		context,
		sceneEnCours,
		pnj: pnjData,
		credits,
		inventaire
	};
}

// ============================================================================
// CONTEXTE INIT (première fois)
// ============================================================================

export function buildContextInit() {
	return 'Nouvelle partie. Lance le jeu. Génère le monde, les personnages, et la scène d\'arrivée.';
}

// ============================================================================
// EXPORTS
// ============================================================================

export {
	formatPnjPresent,
	formatPnjMinimal,
	formatValentin,
	formatSituationActuelle,
	formatResumesScenes,
	formatMessagesScene,
	formatTransactions,
	formatArcs,
	formatAVenir
};
