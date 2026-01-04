/**
 * Context Builder pour LDVELH
 */

import {
	selectionnerFaitsPertinents,
	formaterFaitsPourContexte
} from './faitsService.js';
import {
	calculerSolde,
	calculerInventaire
} from './financeService.js';

// ============================================================================
// EXTRACTION DES NOMS DE PNJ DEPUIS LE TEXTE
// ============================================================================

function extractMentionedPnj(messages, knownPnj) {
	if (!messages || !knownPnj || knownPnj.length === 0) return [];

	const text = messages.map(m => m.content).join(' ').toLowerCase();
	const mentioned = [];

	const isWordPresent = (textToSearch, word) => {
		const escaped = word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
		const regex = new RegExp(`(?:^|[\\s.,!?;:'"«»()\\-])${escaped}(?:[\\s.,!?;:'"«»()\\-]|$)`, 'i');
		return regex.test(textToSearch);
	};

	for (const pnj of knownPnj) {
		if (!pnj.nom) continue;
		const nomLower = pnj.nom.toLowerCase();
		const prenom = pnj.nom.split(' ')[0].toLowerCase();

		if (isWordPresent(text, nomLower)) {
			mentioned.push(pnj.nom);
			continue;
		}
		if (prenom.length >= 3 && isWordPresent(text, prenom)) {
			mentioned.push(pnj.nom);
		}
	}

	return [...new Set(mentioned)];
}

// ============================================================================
// FORMATAGE DES DONNÉES
// ============================================================================

function formatPnjFiche(pnj) {
	let fiche = `## ${pnj.nom.toUpperCase()}`;
	fiche += ` (relation: ${pnj.relation ?? 0}/10, disposition: ${pnj.disposition || 'neutre'})\n`;

	const infos = [];
	if (pnj.age) infos.push(`${pnj.age} ans`);
	if (pnj.metier) infos.push(pnj.metier);
	if (pnj.domicile) infos.push(`vit: ${pnj.domicile}`);
	if (infos.length > 0) fiche += `- ${infos.join(', ')}\n`;

	if (pnj.physique) fiche += `- Physique: ${pnj.physique}\n`;
	if (pnj.traits?.length > 0) fiche += `- Traits: ${pnj.traits.join(', ')}\n`;

	fiche += `- Stats: Social ${pnj.stat_social ?? 3}/5, Travail ${pnj.stat_travail ?? 3}/5, Santé ${pnj.stat_sante ?? 3}/5\n`;

	if (pnj.etape_romantique > 0) {
		const etapes = ['Inconnus', 'Indifférence', 'Reconnaissance', 'Sympathie', 'Curiosité', 'Intérêt', 'Attirance'];
		fiche += `- Étape romantique: ${pnj.etape_romantique}/6 (${etapes[pnj.etape_romantique] || '?'})\n`;
	}

	if (pnj.arc) fiche += `- Arc: "${pnj.arc}"\n`;
	if (pnj.dernier_contact) fiche += `- Dernier contact: cycle ${pnj.dernier_contact}\n`;

	return fiche;
}

function formatArcs(arcs) {
	if (!arcs || arcs.length === 0) return '';
	let section = '=== ARCS NARRATIFS ===\n';
	for (const arc of arcs) {
		if (typeof arc === 'string') { section += `• ${arc}\n`; continue; }
		if (arc.etat && arc.etat !== 'actif') continue;
		section += `• ${arc.nom || 'Arc'} (${arc.type || 'général'}) - ${arc.progression || 0}%\n`;
	}
	return section + '\n';
}

function formatLieux(lieux) {
	if (!lieux || lieux.length === 0) return '';
	let section = '=== LIEUX CONNUS ===\n';
	for (const lieu of lieux.slice(0, 8)) {
		if (typeof lieu === 'string') { section += `• ${lieu}\n`; continue; }
		section += `• ${lieu.nom} (${lieu.type || 'lieu'})`;
		if (lieu.description) section += ` - ${lieu.description}`;
		section += '\n';
	}
	return section + '\n';
}

function formatAVenir(aVenir) {
	if (!aVenir || aVenir.length === 0) return '';
	let section = '=== ÉVÉNEMENTS PLANIFIÉS ===\n';
	for (const ev of aVenir.slice(0, 5)) {
		if (typeof ev === 'string') { section += `• ${ev}\n`; continue; }
		if (ev.realise) continue;
		section += `• [Cycle ${ev.cycle_prevu || '?'}] ${ev.evenement || ev}`;
		if (ev.pnj_impliques?.length > 0) section += ` (avec: ${ev.pnj_impliques.join(', ')})`;
		section += '\n';
	}
	return section + '\n';
}

function formatValentin(valentin, ia, credits, inventaire, lieuActuel) {
	if (!valentin) return '';

	let section = '=== ÉTAT DE VALENTIN ===\n';

	if (lieuActuel) {
		section += `Lieu actuel: ${lieuActuel.nom}`;
		if (lieuActuel.type) section += ` (${lieuActuel.type})`;
		section += '\n';
		if (lieuActuel.description) section += `   ${lieuActuel.description}\n`;
		if (lieuActuel.pnj_frequents?.length > 0) {
			section += `   PNJ fréquents: ${lieuActuel.pnj_frequents.join(', ')}\n`;
		}
	}
	section += `Énergie: ${valentin.energie ?? 3}/5 | Moral: ${valentin.moral ?? 3}/5 | Santé: ${valentin.sante ?? 5}/5\n`;
	section += `Crédits: ${credits ?? 1400}\n`;

	if (inventaire && inventaire.length > 0) {
		section += `Inventaire: ${inventaire.join(', ')}\n`;
	}

	const comp = valentin.competences || {};
	section += `Compétences: Info ${comp.informatique ?? 5}/5, Systèmes ${comp.systemes ?? 4}/5, `;
	section += `Social ${comp.social ?? 2}/5, Cuisine ${comp.cuisine ?? 3}/5, `;
	section += `Bricolage ${comp.bricolage ?? 3}/5, Médical ${comp.medical ?? 1}/5\n`;

	if (valentin.traits?.length > 0) section += `Traits: ${valentin.traits.join(', ')}\n`;
	if (valentin.hobbies?.length > 0) section += `Hobbies: ${valentin.hobbies.join(', ')}\n`;
	if (valentin.poste) section += `Poste: ${valentin.poste}\n`;

	if (ia?.nom) {
		section += `IA: ${ia.nom} (${Array.isArray(ia.traits) ? ia.traits.join(', ') : 'sarcastique'})\n`;
	}

	return section + '\n';
}

// ============================================================================
// CONSTRUCTION DU CONTEXTE
// ============================================================================

function buildContext({
	gameState,
	allPnj = [],
	recentMessages = [],
	cycleResumes = [],
	credits,
	inventaire,
	lieuActuel,
	userMessage
}) {
	let context = '';

	// 1. Résumés des cycles anciens
	if (cycleResumes.length > 0) {
		context += '=== RÉSUMÉS CYCLES PRÉCÉDENTS ===\n';
		for (const r of cycleResumes) {
			context += `[Cycle ${r.cycle}${r.jour ? ', ' + r.jour : ''}] ${r.resume}\n`;
		}
		context += '\n';
	}

	// 2. État de Valentin (avec crédits et inventaire calculés)
	context += formatValentin(gameState?.valentin, gameState?.ia, credits, inventaire, lieuActuel);

	// 3. PNJ
	const mentionedPnjNames = extractMentionedPnj(recentMessages, allPnj);
	const currentCycle = gameState?.partie?.cycle_actuel || 1;

	const pnjToInclude = allPnj.length <= 5
		? allPnj
		: allPnj.filter(p =>
			mentionedPnjNames.includes(p.nom) ||
			p.est_initial ||
			p.interet_romantique ||
			(p.dernier_contact && p.dernier_contact >= currentCycle - 2)
		);

	if (pnjToInclude.length > 0) {
		context += '=== PERSONNAGES ===\n';
		for (const pnj of pnjToInclude) {
			context += formatPnjFiche(pnj) + '\n';
		}
	}

	// 4. Arcs
	if (gameState?.arcs) context += formatArcs(gameState.arcs);

	// 5. Lieux
	if (gameState?.lieux) context += formatLieux(gameState.lieux);

	// 6. Événements à venir
	if (gameState?.aVenir) context += formatAVenir(gameState.aVenir);

	// 7. Messages récents
	if (recentMessages.length > 0) {
		context += '=== CONVERSATION RÉCENTE ===\n';
		context += '(IMPORTANT: Maintiens une cohérence ABSOLUE avec ces échanges)\n\n';
		for (const m of recentMessages.slice(-20)) {
			const role = m.role === 'user' ? 'VALENTIN' : 'MJ';
			const content = m.content.length > 800 ? m.content.slice(0, 800) + '...' : m.content;
			context += `${role}: ${content}\n\n`;
		}
	}

	// 8. Action actuelle
	context += '=== ACTION DU JOUEUR ===\n';
	context += userMessage;

	return context;
}

// ============================================================================
// FONCTION PRINCIPALE
// ============================================================================

async function buildContextForClaude(
	supabase,
	partieId,
	gameState,
	userMessage,
	preloadedPnj = null,
	options = {}
) {
	const { faitsEnabled = true } = options;

	// Cycle actuel depuis le state
	const currentCycle = gameState?.partie?.cycle_actuel || 1;

	// Lieu actuel depuis le state
	const lieuActuelNom = gameState?.partie?.lieu_actuel || '';

	// Requêtes en parallèle
	const [pnjResult, messagesResult, resumesResult, lieuActuelResult] = await Promise.all([
		preloadedPnj
			? Promise.resolve({ data: preloadedPnj })
			: supabase.from('pnj').select('*').eq('partie_id', partieId)
				.order('dernier_contact', { ascending: false, nullsFirst: false }),
		supabase.from('chat_messages').select('role, content, cycle, created_at')
			.eq('partie_id', partieId).gte('cycle', Math.max(1, currentCycle - 1))
			.order('created_at', { ascending: true }),
		supabase.from('cycle_resumes').select('cycle, jour, date_jeu, resume, evenements_cles')
			.eq('partie_id', partieId).lt('cycle', currentCycle)
			.order('cycle', { ascending: false }).limit(3),
		lieuActuelNom
			? supabase.from('lieux').select('*').eq('partie_id', partieId)
				.ilike('nom', lieuActuelNom).maybeSingle()
			: Promise.resolve({ data: null })
	]);

	const pnjData = pnjResult?.data || [];
	const messagesData = messagesResult?.data || [];
	const resumesData = resumesResult?.data || [];
	const lieuActuel = lieuActuelResult?.data || null;

	const currentCycleMessages = messagesData.filter(m => m.cycle === currentCycle);
	const previousCycleMessages = messagesData.filter(m => m.cycle === currentCycle - 1).slice(-4);
	const recentMessages = [...previousCycleMessages, ...currentCycleMessages];

	// Calculer crédits et inventaire depuis finances
	const [credits, inventaire] = await Promise.all([
		calculerSolde(supabase, partieId, gameState?.valentin?.credits || 1400),
		calculerInventaire(supabase, partieId)
	]);

	// Faits
	let faitsData = [];
	let faitsContexte = '';

	if (faitsEnabled) {
		try {
			const mentionedPnjNames = extractMentionedPnj(recentMessages, pnjData);

			faitsData = await selectionnerFaitsPertinents(supabase, partieId, {
				pnjPresents: mentionedPnjNames,
				lieuActuel: lieuActuel,
				cycleActuel: currentCycle,
				budgetTokens: 3000
			});

			if (faitsData.length > 0) {
				faitsContexte = formaterFaitsPourContexte(faitsData);
			}
		} catch (err) {
			console.error('[Context] Erreur chargement faits:', err);
		}
	}

	// Construire le contexte
	let context = buildContext({
		gameState,
		allPnj: pnjData,
		recentMessages,
		cycleResumes: resumesData.reverse(),
		credits,
		inventaire,
		lieuActuel,
		userMessage
	});

	// Injecter les faits au début
	if (faitsContexte) {
		const insertionPoint = context.indexOf('=== ÉTAT DE VALENTIN ===');
		if (insertionPoint > 0) {
			context = context.slice(0, insertionPoint) + faitsContexte + '\n' + context.slice(insertionPoint);
		} else {
			context = faitsContexte + '\n' + context;
		}
	}

	return { context, pnj: pnjData, faits: faitsData, credits, inventaire };
}

// ============================================================================
// EXPORTS
// ============================================================================

export {
	buildContext,
	buildContextForClaude,
	extractMentionedPnj,
	formatPnjFiche,
	formatArcs,
	formatLieux,
	formatAVenir,
	formatValentin
};
