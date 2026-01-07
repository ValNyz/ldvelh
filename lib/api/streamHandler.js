/**
 * Gestion du streaming SSE pour les réponses Claude
 */

import { StreamError } from '../errors.js';
import { MODELS, API_CONFIG } from '../constants.js';
import {
	parseAndValidate,
	detectSuspiciousStructure
} from './responseParser.js';
import { buildDisplayFromPartial, buildDisplayText } from '../utils/displayBuilder.js';

// ============================================================================
// TYPES D'ÉVÉNEMENTS SSE
// ============================================================================

export const SSE_EVENTS = {
	CHUNK: 'chunk',           // Fragment de réponse
	DONE: 'done',             // Génération terminée
	SAVED: 'saved',           // Sauvegarde terminée
	ERROR: 'error',           // Erreur
	WARNING: 'warning',       // Avertissement (non bloquant)
	STATE_UPDATE: 'state'     // Mise à jour d'état
};

// ============================================================================
// CLASSE STREAM WRITER
// ============================================================================

export class SSEWriter {
	constructor() {
		const { readable, writable } = new TransformStream();
		this.readable = readable;
		this.writer = writable.getWriter();
		this.encoder = new TextEncoder();
		this.closed = false;
	}

	/**
	 * Envoie un événement SSE
	 * @param {string} type - Type d'événement
	 * @param {object} data - Données à envoyer
	 */
	async send(type, data) {
		if (this.closed) {
			console.warn('[SSE] Tentative d\'écriture sur stream fermé');
			return;
		}

		try {
			const event = JSON.stringify({ type, ...data });
			await this.writer.write(
				this.encoder.encode(`data: ${event}\n\n`)
			);
		} catch (e) {
			console.error('[SSE] Erreur écriture:', e);
		}
	}

	/**
	 * Envoie un chunk de contenu
	 */
	async sendChunk(content) {
		await this.send(SSE_EVENTS.CHUNK, { content });
	}

	/**
	 * Envoie la réponse finale
	 */
	async sendDone(displayText, state = null) {
		await this.send(SSE_EVENTS.DONE, { displayText, state });
	}

	/**
	 * Envoie une confirmation de sauvegarde
	 */
	async sendSaved() {
		await this.send(SSE_EVENTS.SAVED, {});
	}

	/**
	 * Envoie une erreur
	 */
	async sendError(error, details = null, recoverable = false) {
		await this.send(SSE_EVENTS.ERROR, {
			error,
			details,
			recoverable
		});
	}

	/**
	 * Envoie un warning
	 */
	async sendWarning(message, details = null) {
		await this.send(SSE_EVENTS.WARNING, { message, details });
	}

	/**
	 * Ferme le stream
	 */
	async close() {
		if (this.closed) return;

		try {
			await this.writer.close();
			this.closed = true;
		} catch (e) {
			console.error('[SSE] Erreur fermeture:', e);
		}
	}

	/**
	 * Crée la Response HTTP
	 */
	getResponse() {
		return new Response(this.readable, {
			headers: {
				'Content-Type': 'text/event-stream',
				'Cache-Control': 'no-cache, no-transform',
				'Connection': 'keep-alive'
			}
		});
	}
}

// ============================================================================
// HANDLER DE STREAMING CLAUDE
// ============================================================================

/**
 * Gère le streaming d'une réponse Claude
 * @param {object} options
 * @param {object} options.anthropic - Client Anthropic
 * @param {string} options.model - Modèle à utiliser
 * @param {string} options.systemPrompt - Prompt système
 * @param {string} options.userMessage - Message utilisateur
 * @param {number} options.maxTokens - Tokens max
 * @param {'init'|'light'} options.mode - Mode de validation
 * @param {SSEWriter} options.sseWriter - Writer SSE
 * @param {Function} options.onComplete - Callback avec (parsed, displayText, fullJson)
 */
export async function streamClaudeResponse(options) {
	const {
		anthropic,
		model,
		systemPrompt,
		userMessage,
		maxTokens,
		mode,
		sseWriter,
		onComplete
	} = options;

	let fullJson = '';
	let lastSentDisplay = '';
	let assistantStarted = false;
	const streamStart = Date.now();

	try {
		console.log(`[STREAM] Contexte:`, userMessage)
		console.log(`[STREAM] Démarrage (mode: ${mode})...`);

		const streamResponse = await anthropic.messages.stream({
			model,
			temperature: API_CONFIG.TEMPERATURE,
			max_tokens: maxTokens,
			system: [{
				type: 'text',
				text: systemPrompt,
				cache_control: { type: 'ephemeral' }
			}],
			messages: [{ role: 'user', content: userMessage }]
		});

		// Traitement des chunks
		for await (const event of streamResponse) {
			if (event.type === 'content_block_delta' && event.delta?.text) {
				fullJson += event.delta.text;

				const displayableContent = buildDisplayFromPartial(fullJson);
				if (displayableContent && displayableContent !== lastSentDisplay) {
					await sseWriter.sendChunk(displayableContent);
					lastSentDisplay = displayableContent;
				}

				// Détecter structure suspecte
				if (!assistantStarted && fullJson.length > 500) {
					if (detectSuspiciousStructure(fullJson, mode)) {
						await sseWriter.sendWarning('Structure de réponse inhabituelle détectée');
					}
					assistantStarted = true;
				}
			}
		}

		console.log(`[STREAM] Terminé: ${Date.now() - streamStart}ms, ${fullJson.length} chars`);

		// Parser et valider
		const { success, parsed, errors, warnings, rawParsed } = parseAndValidate(fullJson, mode);

		console.log(`[STREAM] Parsed:`, JSON.stringify(parsed, null, 2))

		// Log warnings
		if (warnings?.length > 0) {
			console.warn('[STREAM] Validation warnings:', warnings);
			await sseWriter.sendWarning('Réponse partiellement validée', warnings);
		}

		// Construire le texte d'affichage
		let displayText;
		if (parsed?.narratif) {
			displayText = buildDisplayText(parsed);
		} else {
			// Fallback : extraire ce qu'on peut
			displayText = buildDisplayFromPartial(fullJson) ||
				fullJson.replace(/```json[\s\S]*?```/g, '').trim() ||
				'Erreur de génération.';
		}

		// Erreurs critiques
		if (!success && !parsed?.narratif) {
			console.error('[STREAM] Validation échouée:', errors);
			await sseWriter.sendError(
				'Réponse invalide du modèle',
				errors,
				true // recoverable
			);
		}

		// Appeler le callback
		await onComplete(parsed || rawParsed, displayText, fullJson);

	} catch (error) {
		console.error('[STREAM] Erreur:', error);

		// Si on a du contenu partiel, essayer de l'utiliser
		if (fullJson.length > 100) {
			const displayText = buildDisplayFromPartial(fullJson);
			if (displayText) {
				await onComplete(null, displayText + '\n\n*(Réponse interrompue)*', fullJson);
			}
		}

		throw new StreamError(error.message, 'streaming');
	}
}

// ============================================================================
// HELPERS
// ============================================================================

/**
 * Crée un handler de streaming complet
 */
export function createStreamHandler() {
	const sseWriter = new SSEWriter();

	return {
		sseWriter,
		response: sseWriter.getResponse(),

		async stream(options) {
			try {
				await streamClaudeResponse({
					...options,
					sseWriter
				});
			} finally {
				await sseWriter.close();
			}
		}
	};
}
