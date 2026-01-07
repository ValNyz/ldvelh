/**
 * Resume Extractor
 * Génère un résumé court de la scène
 */

import Anthropic from '@anthropic-ai/sdk';
import { MODELS, API_CONFIG } from '../../constants.js';

import { extractJSON } from '../../api/responseParser.js'

const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

const RESUME_SCHEMA = {
	type: 'object',
	properties: {
		resume: {
			type: 'string',
		}
	},
	required: ['resume']
};

const PROMPT_RESUME = `Résume ce message de jeu en 2-4 phrases.
Capture : les actions principales, les interactions clés, les décisions du joueur, les faits.
Style : factuel, concis, passé composé.

Réponds UNIQUEMENT en JSON : { "resume": "..." }`;

/**
 * Extrait un résumé du narratif
 * @param {string} narratif - Le texte de la scène
 * @returns {Promise<{success: boolean, resume?: string, error?: string}>}
 */
export async function extractResume(narratif) {
	const start = Date.now();

	try {
		const response = await anthropic.messages.create({
			model: MODELS.EXTRACTION,
			max_tokens: API_CONFIG.MAX_TOKENS_RESUME,
			system: [{
				type: 'text',
				text: PROMPT_RESUME,
				cache_control: { type: 'ephemeral' }
			}],
			messages: [{ role: 'user', content: narratif }],
		});

		const parsed = extractJSON(response.content[0]?.text);

		if (!parsed?.resume) {
			return { success: false, error: 'Pas de résumé généré' };
		}

		console.log(`[Resume] OK en ${Date.now() - start}ms`);
		return { success: true, resume: parsed.resume };

	} catch (err) {
		console.error('[Resume] Erreur:', err.message);
		return { success: false, error: err.message };
	}
}
