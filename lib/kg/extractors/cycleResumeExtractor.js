/**
 * Cycle Resume Extractor
 * Génère un résumé de la journée à partir des résumés individuels des messages
 */

import Anthropic from '@anthropic-ai/sdk';
import { MODELS, API_CONFIG } from '../../constants.js';

import { extractJSON } from '../../api/responseParser.js'

const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

const CYCLE_RESUME_SCHEMA = {
	type: 'object',
	properties: {
		resume: {
			type: 'string',
			description: 'Résumé synthétique de la journée en 3-5 phrases. Capture les faits majeurs, les événements majeurs, décisions importantes, rencontres significatives et évolutions narratives.'
		},
		evenements_cles: {
			type: 'array',
			items: { type: 'string' },
			description: 'Liste des 3-5 événements les plus importants de la journée'
		},
		pnjs_rencontres: {
			type: 'array',
			items: { type: 'string' },
			description: 'Noms des PNJ avec qui Valentin a interagi'
		},
		lieux_visites: {
			type: 'array',
			items: { type: 'string' },
			description: 'Lieux visités durant la journée'
		},
		ton_general: {
			type: 'string',
			enum: ['positif', 'neutre', 'negatif', 'mitige'],
			description: 'Tonalité générale de la journée'
		}
	},
	required: ['resume', 'evenements_cles', 'pnjs_rencontres', 'lieux_visites', 'ton_general']
};

const SYSTEM_PROMPT = `Tu es un assistant qui synthétise les événements d'une journée de jeu de rôle.

À partir des résumés individuels des échanges, génère un résumé cohérent de la journée.

Règles :
- Style factuel, passé composé
- Capture l'essence narrative, pas les détails
- Mentionne les relations qui ont évolué
- Note les décisions importantes du joueur
- Reste concis mais informatif`;

/**
 * Génère un résumé de cycle à partir des résumés des messages
 * @param {object} supabase - Client Supabase
 * @param {string} partieId - ID de la partie
 * @param {number} cycle - Numéro du cycle à résumer
 * @param {object} infosJour - {jour, date_jeu} du cycle
 * @returns {Promise<{success: boolean, data?: object, error?: string}>}
 */
export async function extractCycleResume(supabase, partieId, cycle, infosJour = {}) {
	const start = Date.now();

	try {
		// 1. Récupérer tous les résumés du cycle
		const { data: messages, error } = await supabase
			.from('chat_messages')
			.select('resume, lieu, pnjs_presents')
			.eq('partie_id', partieId)
			.eq('cycle', cycle)
			.eq('role', 'assistant')
			.not('resume', 'is', null)
			.order('created_at', { ascending: true });

		if (error) {
			console.error('[CycleResume] Erreur fetch messages:', error);
			return { success: false, error: error.message };
		}

		if (!messages?.length) {
			console.log('[CycleResume] Aucun résumé à synthétiser');
			return { success: false, error: 'Aucun résumé disponible' };
		}

		// 2. Construire le contexte
		const resumesConcatenes = messages.map((m, i) => `${i + 1}. ${m.resume}`).join('\n');
		const lieuxUniques = [...new Set(messages.map(m => m.lieu).filter(Boolean))];
		const pnjsUniques = [...new Set(messages.flatMap(m => m.pnjs_presents || []))];

		const userMessage = `Journée: ${infosJour.jour || 'Jour ' + cycle} ${infosJour.date_jeu || ''}

Lieux visités: ${lieuxUniques.join(', ') || 'Non spécifié'}
PNJ rencontrés: ${pnjsUniques.join(', ') || 'Aucun'}

Résumés des échanges:
${resumesConcatenes}`;

		// 3. Appel API avec structured output
		const response = await anthropic.messages.create({
			model: MODELS.EXTRACTION,
			max_tokens: API_CONFIG.MAX_TOKENS_EXTRACTION,
			system: [{
				type: 'text',
				text: SYSTEM_PROMPT,
				cache_control: { type: 'ephemeral' }
			}],
			messages: [{ role: 'user', content: userMessage }],
		});

		const parsed = extractJSON(response.content[0]?.text);

		// 4. Sauvegarder dans cycle_resumes
		const { error: insertError } = await supabase
			.from('cycle_resumes')
			.insert({
				partie_id: partieId,
				cycle,
				jour: infosJour.jour,
				date_jeu: infosJour.date_jeu,
				resume: parsed.resume,
				evenements_cles: parsed.evenements_cles,
				relations_modifiees: {
					pnjs_rencontres: parsed.pnjs_rencontres,
					lieux_visites: parsed.lieux_visites,
					ton_general: parsed.ton_general
				}
			});

		if (insertError) {
			console.error('[CycleResume] Erreur insert:', insertError);
			return { success: false, error: insertError.message };
		}

		console.log(`[CycleResume] Cycle ${cycle} résumé en ${Date.now() - start}ms`);

		return {
			success: true,
			data: parsed
		};

	} catch (err) {
		console.error('[CycleResume] Erreur:', err.message);
		return { success: false, error: err.message };
	}
}
