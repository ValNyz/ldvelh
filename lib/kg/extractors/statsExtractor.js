/**
 * Stats Extractor
 * Extrait les changements de jauges de Valentin (énergie, moral, santé)
 */

import Anthropic from '@anthropic-ai/sdk';
import { MODELS } from '../../constants.js';

import { extractJSON } from '../../api/responseParser.js'

const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

const STATS_SCHEMA = {
	type: 'object',
	properties: {
		energie: {
			type: 'number',
			description: 'Delta énergie: effort→-, repos/repas→+. Valeurs: -2, -1.5, -1, -0.5, 0, 0.5, 1, 1.5, 2'
		},
		moral: {
			type: 'number',
			description: 'Delta moral: échec/rejet→-, succès/connexion→+. Valeurs: -2, -1.5, -1, -0.5, 0, 0.5, 1, 1.5, 2'
		},
		sante: {
			type: 'number',
			description: 'Delta santé: blessure→-, soin→+. Valeurs: -2, -1.5, -1, -0.5, 0, 0.5, 1, 1.5, 2'
		}
	},
	required: ['energie', 'moral', 'sante']
};

const PROMPT_STATS = `Deltas jauges Valentin (1-5). 80% des scènes = tous à 0 (routine, rien de notable).

Énergie (fatigue physique): effort→-, repos/repas→+
Moral (état émotionnel, fatigue mentale): échec/rejet→-, succès/connexion→+
Santé (état physique): blessure→-, soin→+

Deltas: ±0.5 léger, ±1 modéré, ±1.5 fort, ±2 rare/majeur

JSON uniquement: { "energie": 0, "moral": 0, "sante": 0 }`;

/**
 * Extrait les deltas de stats depuis le narratif
 * @param {string} narratif 
 * @param {{energie: number, moral: number, sante: number}} statsActuelles
 * @returns {Promise<{success: boolean, deltas?: object, error?: string}>}
 */
export async function extractStats(narratif, statsActuelles) {
	const start = Date.now();

	try {
		const context = `## STATS ACTUELLES
Énergie: ${statsActuelles.energie}/5
Moral: ${statsActuelles.moral}/5
Santé: ${statsActuelles.sante}/5

## NARRATIF
${narratif}`;

		const response = await anthropic.messages.create({
			model: MODELS.EXTRACTION,
			max_tokens: 100,
			system: [{
				type: 'text',
				text: PROMPT_STATS,
				cache_control: { type: 'ephemeral' }
			}],
			messages: [{ role: 'user', content: context }],
		});

		const parsed = extractJSON(response.content[0]?.text);

		if (!parsed) {
			return { success: false, error: 'JSON invalide' };
		}

		// Valider et borner les deltas
		const deltas = {
			energie: clampDelta(parsed.energie),
			moral: clampDelta(parsed.moral),
			sante: clampDelta(parsed.sante)
		};

		// Vérifier que les nouvelles valeurs restent dans [1, 5]
		const validated = {
			energie: wouldExceedBounds(statsActuelles.energie, deltas.energie) ? 0 : deltas.energie,
			moral: wouldExceedBounds(statsActuelles.moral, deltas.moral) ? 0 : deltas.moral,
			sante: wouldExceedBounds(statsActuelles.sante, deltas.sante) ? 0 : deltas.sante
		};

		const hasChanges = validated.energie !== 0 || validated.moral !== 0 || validated.sante !== 0;

		console.log(`[Stats] ${hasChanges ? `E:${validated.energie} M:${validated.moral} S:${validated.sante}` : 'pas de changement'} en ${Date.now() - start}ms`);

		return { success: true, deltas: validated };

	} catch (err) {
		console.error('[Stats] Erreur:', err.message);
		return { success: false, error: err.message };
	}
}

function clampDelta(val) {
	const num = parseFloat(val) || 0;
	// Arrondir à 0.5 près et borner à ±2
	const rounded = Math.round(num * 2) / 2;
	return Math.max(-2, Math.min(2, rounded));
}

function wouldExceedBounds(current, delta) {
	const next = current + delta;
	return next < 1 || next > 5;
}
