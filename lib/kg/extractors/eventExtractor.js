/**
 * Event Extractor
 * Extrait les événements passés et les RDV planifiés
 */

import Anthropic from '@anthropic-ai/sdk';
import { MODELS, API_CONFIG } from '../../constants.js';

const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });


const PROMPT_EVENTS = `Extrais événements passés et RDV planifiés. Si rien: { "evenements_passes": [], "evenements_planifies": [], "annulations": [] }

ÉVÉNEMENT PASSÉ : Ce qui VIENT de se passer (significatif uniquement):
{ "op": "CREER_EVENEMENT", "titre": "...", "categorie": "social|travail|achat|decouverte|conflit|romantique", "lieu": "...", "participants": ["..."] }

RDV PLANIFIÉ (engagement temporel clair: "demain", "à 14h", "lundi"):
{ "op": "PLANIFIER_EVENEMENT", "titre": "RDV avec X", "categorie": "...", "cycle_prevu": N, "heure": "14h00", "lieu": "...", "participants": ["..."] }

Récurrent: ajouter "recurrence": {"frequence": "hebdo", "jour": "lundi"}

NE PAS extraire si vague: "un de ces jours", "peut-être", "on pourrait"

ANNULATION:
{ "op": "ANNULER_EVENEMENT", "titre": "(Copie EXACTE du contexte)", "raison": "..." }

FORMAT: { "evenements_passes": [...], "evenements_planifies": [...], "annulations": [...] }`;

/**
 * Extrait les événements depuis le narratif
 * @param {string} narratif 
 * @param {number} cycle - Cycle actuel
 * @param {string} jour - Jour actuel (ex: "Mercredi")
 * @param {string} date_jeu - Date actuelle
 * @param {Array} rdvExistants - RDV déjà planifiés
 * @returns {Promise<{success: boolean, evenements_passes?: Array, evenements_planifies?: Array, annulations?: Array, error?: string}>}
 */
export async function extractEvents(narratif, cycle, jour, date_jeu, rdvExistants) {
	const start = Date.now();

	try {
		const context = buildContext(narratif, cycle, jour, date_jeu, rdvExistants);

		const response = await anthropic.messages.create({
			model: MODELS.EXTRACTION,
			max_tokens: API_CONFIG.MAX_TOKENS_EXTRACTION,
			system: [{
				type: 'text',
				text: PROMPT_EVENTS,
				cache_control: { type: 'ephemeral' }
			}],
			messages: [{ role: 'user', content: context }]
		});

		const content = response.content[0]?.text;
		const parsed = parseJSON(content);

		if (!parsed) {
			return { success: false, error: 'JSON invalide' };
		}

		const evenements_passes = (parsed.evenements_passes || []).filter(e => e.op && e.titre);
		const evenements_planifies = (parsed.evenements_planifies || [])
			.filter(e => e.op && e.titre && e.cycle_prevu)
			.map(e => ({ ...e, cycle_prevu: e.cycle_prevu || cycle }));
		const annulations = (parsed.annulations || []).filter(e => e.op && e.titre);

		const total = evenements_passes.length + evenements_planifies.length + annulations.length;
		console.log(`[Events] ${total} événements en ${Date.now() - start}ms`);

		return {
			success: true,
			evenements_passes,
			evenements_planifies,
			annulations
		};

	} catch (err) {
		console.error('[Events] Erreur:', err.message);
		return { success: false, error: err.message };
	}
}

function buildContext(narratif, cycle, jour, date_jeu, rdvExistants) {
	let ctx = `## TEMPS ACTUEL\n`;
	ctx += `Cycle: ${cycle}`;
	if (jour) ctx += ` | ${jour}`;
	if (date_jeu) ctx += ` | ${date_jeu}`;
	ctx += '\n\n';

	// Mapping des jours pour calculer cycle_prevu
	const jours = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche'];
	const jourActuelIndex = jour ? jours.findIndex(j =>
		jour.toLowerCase().startsWith(j.toLowerCase())
	) : 0;

	ctx += `## MAPPING JOURS → CYCLES\n`;
	const mappings = [];
	for (let i = 0; i < 7; i++) {
		const jourIndex = (jourActuelIndex + i) % 7;
		const label = i === 0 ? 'Aujourd\'hui' : (i === 1 ? 'Demain' : jours[jourIndex]);
		mappings.push(`${label} = cycle ${cycle + i}`);
	}
	ctx += mappings.join('\n') + '\n\n';

	if (rdvExistants?.length > 0) {
		ctx += `## RDV DÉJÀ PLANIFIÉS (ne pas dupliquer)\n`;
		for (const rdv of rdvExistants) {
			ctx += `- Cycle ${rdv.cycle}${rdv.heure ? ' ' + rdv.heure : ''}: ${rdv.titre}`;
			if (rdv.participants?.length > 0) {
				const autres = rdv.participants.filter(p => p.toLowerCase() !== 'valentin');
				if (autres.length > 0) ctx += ` (avec ${autres.join(', ')})`;
			}
			ctx += '\n';
		}
		ctx += '\n';
	}

	ctx += `## NARRATIF\n${narratif}`;

	return ctx;
}

function parseJSON(str) {
	if (!str) return null;
	try {
		let cleaned = str.trim();
		if (cleaned.startsWith('```')) {
			cleaned = cleaned.replace(/```json?\n?/g, '').replace(/```$/g, '');
		}
		return JSON.parse(cleaned);
	} catch {
		return null;
	}
}
