/**
 * Stats Extractor
 * Extrait les changements de jauges de Valentin (énergie, moral, santé)
 */

import Anthropic from '@anthropic-ai/sdk';
import { MODELS } from '../../constants.js';

const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

const PROMPT_STATS = `Analyse l'impact de cette scène sur l'état de Valentin.

## JAUGES (échelle 1-5)

**Énergie** (fatigue physique/mentale)
- Effort physique, marche longue, travail intense → négatif
- Repos, sieste, repas copieux → positif
- Conversation normale, observation → neutre (0)

**Moral** (état émotionnel)  
- Rejet, échec, mauvaise nouvelle, solitude → négatif
- Moment agréable, succès, connexion sociale → positif
- Routine, interactions neutres → neutre (0)

**Santé** (état physique)
- Blessure, maladie, excès → négatif
- Soin, médicament, récupération → positif
- Normal → neutre (0)

## BARÈMES
- ±0.5 : impact léger (fatigue mineure, légère contrariété)
- ±1 : impact modéré (effort significatif, bonne/mauvaise nouvelle)
- ±1.5 : impact fort (épuisement, choc émotionnel)
- ±2 : impact majeur (rare, événement marquant)

80% des scènes = deltas à 0 (routine, rien de notable)

Réponds UNIQUEMENT en JSON :
{ "energie": 0, "moral": 0, "sante": 0 }`;

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
			messages: [{ role: 'user', content: context }]
		});

		const content = response.content[0]?.text;
		const parsed = parseJSON(content);

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
