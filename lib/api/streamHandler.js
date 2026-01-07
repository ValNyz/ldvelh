/**
 * Gestion du streaming SSE pour les réponses Claude
 */

import { StreamError } from '../errors.js';
import { API_CONFIG } from '../constants.js';
import {
	parseAndValidate,
	detectSuspiciousStructure
} from './responseParser.js';
import { buildDisplayFromPartial, buildDisplayText } from '../utils/displayBuilder.js';

// ============================================================================
// TYPES D'ÉVÉNEMENTS SSE
// ============================================================================

export const SSE_EVENTS = {
	CHUNK: 'chunk',
	PROGRESS: 'progress',
	DONE: 'done',
	SAVED: 'saved',
	ERROR: 'error',
	WARNING: 'warning',
	STATE_UPDATE: 'state'
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

	async send(type, data) {
		if (this.closed) return;

		try {
			const event = JSON.stringify({ type, ...data });
			await this.writer.write(
				this.encoder.encode(`data: ${event}\n\n`)
			);
		} catch (e) {
			// Client a fermé la connexion - marquer comme fermé silencieusement
			this.closed = true;
		}
	}

	async sendChunk(content) {
		await this.send(SSE_EVENTS.CHUNK, { content });
	}

	async sendProgress(rawJson) {
		await this.send(SSE_EVENTS.PROGRESS, { rawJson });
	}

	async sendDone(displayText, state = null) {
		await this.send(SSE_EVENTS.DONE, { displayText, state });
	}

	async sendSaved() {
		await this.send(SSE_EVENTS.SAVED, {});
	}

	async sendError(error, details = null, recoverable = false) {
		await this.send(SSE_EVENTS.ERROR, { error, details, recoverable });
	}

	async sendWarning(message, details = null) {
		await this.send(SSE_EVENTS.WARNING, { message, details });
	}

	async close() {
		if (this.closed) return;
		this.closed = true;

		try {
			await this.writer.close();
		} catch (e) {
			// Ignorer - stream déjà fermé par le client
		}
	}

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
	let lastProgressLength = 0;
	let assistantStarted = false;
	const streamStart = Date.now();

	const isInitMode = mode === 'init';

	try {
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

		for await (const event of streamResponse) {
			if (event.type === 'content_block_delta' && event.delta?.text) {
				fullJson += event.delta.text;

				if (isInitMode) {
					if (fullJson.length - lastProgressLength > 500) {
						await sseWriter.sendProgress(fullJson);
						lastProgressLength = fullJson.length;
					}
				} else {
					const displayableContent = buildDisplayFromPartial(fullJson);
					if (displayableContent && displayableContent !== lastSentDisplay) {
						await sseWriter.sendChunk(displayableContent);
						lastSentDisplay = displayableContent;
					}
				}

				if (!assistantStarted && fullJson.length > 500) {
					if (detectSuspiciousStructure(fullJson, mode)) {
						await sseWriter.sendWarning('Structure de réponse inhabituelle détectée');
					}
					assistantStarted = true;
				}
			}
		}

		if (isInitMode && fullJson.length > lastProgressLength) {
			await sseWriter.sendProgress(fullJson);
		}

		console.log(`[STREAM] Terminé: ${Date.now() - streamStart}ms, ${fullJson.length} chars`);

		const { success, parsed, errors, warnings, rawParsed } = parseAndValidate(fullJson, mode);

		if (warnings?.length > 0) {
			console.warn('[STREAM] Validation warnings:', warnings);
			await sseWriter.sendWarning('Réponse partiellement validée', warnings);
		}

		let displayText = null;
		if (!isInitMode) {
			if (parsed?.narratif) {
				displayText = buildDisplayText(parsed);
			} else {
				displayText = buildDisplayFromPartial(fullJson) ||
					fullJson.replace(/```json[\s\S]*?```/g, '').trim() ||
					'Erreur de génération.';
			}
		}

		if (!success && (!isInitMode && !parsed?.narratif)) {
			console.error('[STREAM] Validation échouée:', errors);
			await sseWriter.sendError('Réponse invalide du modèle', errors, true);
		}

		await onComplete(parsed || rawParsed, displayText, fullJson);

	} catch (error) {
		console.error('[STREAM] Erreur:', error);

		if (fullJson.length > 100 && !isInitMode) {
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
