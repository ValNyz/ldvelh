/**
 * LDVELH - /chat stream client (pure, no React)
 *
 * One POST answered with SSE events. Guarantee for the UI: a stream that is not
 * aborted always ends with exactly one terminal event (done | error | roll_pending),
 * synthesized when the server gives none (HTTP error, non-SSE error body, stream
 * cut short), so the caller's "turn in progress" state can never stay stuck (#35).
 *
 * Synthesized events:
 * - { type: 'error', error, status }              HTTP error
 * - { type: 'error', error, interrupted: true }    stream closed without a terminal event
 * (`details` stays what the server sends: text shown under the error.)
 * - { type: 'save_unconfirmed' }                          'done' came but 'saved' never did
 */

import { createSSEParser } from './sse.mjs';

export const STREAM_INTERRUPTED = 'La connexion a été interrompue avant la fin de la réponse. Tu peux réessayer.';
export const SESSION_EXPIRED = 'Session expirée : reconnecte-toi.';

const TERMINAL = new Set(['done', 'error', 'roll_pending']);

/**
 * @param {Object} opts
 * @param {string} opts.url
 * @param {Object} opts.body
 * @param {AbortSignal} [opts.signal]
 * @param {(event: Object) => void} opts.onEvent - every event, received or synthesized
 * @param {() => Object} opts.getHeaders - auth headers, read again after a refresh
 * @param {() => Promise} [opts.refreshSession] - refreshes the token; rejects when the session is over
 * @param {typeof fetch} [opts.fetchImpl]
 * @returns {Promise<{ success: boolean, aborted?: boolean, interrupted?: boolean, status?: number }>}
 */
export async function runChatStream({ url, body, signal, onEvent, getHeaders, refreshSession, fetchImpl = fetch }) {
	const seen = new Set(); // event types received or synthesized
	const ended = () => [...TERMINAL].some(t => seen.has(t));
	const emit = (event) => {
		seen.add(event.type);
		onEvent(event);
	};
	const post = () => fetchImpl(url, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json', ...getHeaders() },
		body: JSON.stringify(body),
		signal,
	});

	try {
		let res = await post();
		if (res.status === 401 && refreshSession) {
			try {
				await refreshSession();
			} catch {
				emit({ type: 'error', error: SESSION_EXPIRED, status: 401 });
				return { success: false, status: 401 };
			}
			res = await post();
		}

		if (!res.ok) {
			emit({ type: 'error', error: await errorMessage(res), status: res.status });
			return { success: false, status: res.status };
		}

		if (!res.headers.get('content-type')?.includes('text/event-stream')) {
			const data = await res.json().catch(() => ({}));
			emit(data.error
				? { type: 'error', error: data.error, details: data.details }
				: { type: 'done', displayText: data.displayText || data.content, state: data.state });
			return { success: !data.error };
		}

		await readEvents(res.body, emit);

		if (!ended()) {
			emit({ type: 'error', error: STREAM_INTERRUPTED, interrupted: true });
			return { success: false, interrupted: true };
		}
		if (seen.has('done') && !seen.has('saved') && !seen.has('error')) emit({ type: 'save_unconfirmed' });
		return { success: !seen.has('error') };
	} catch (e) {
		if (e.name === 'AbortError') return { success: false, aborted: true };
		// Network failure, or the stream broke mid-read: same as an interrupted stream
		if (!ended()) emit({ type: 'error', error: e.message || STREAM_INTERRUPTED, interrupted: true });
		return { success: false, interrupted: true };
	}
}

async function readEvents(stream, emit) {
	const reader = stream.getReader();
	const decoder = new TextDecoder();
	// Buffers partial events across reads (#14)
	const parser = createSSEParser(emit);
	while (true) {
		const { done, value } = await reader.read();
		if (done) break;
		parser.push(decoder.decode(value, { stream: true }));
	}
	parser.push(decoder.decode());
	parser.flush();
}

// FastAPI errors are { detail } (string, or a list for 422); ours may be { error }.
async function errorMessage(res) {
	const data = await res.json().catch(() => null);
	const detail = data?.error || data?.detail;
	if (typeof detail === 'string') return detail;
	if (Array.isArray(detail) && detail[0]?.msg) return `Requête invalide : ${detail[0].msg}`;
	return `Erreur serveur (${res.status}${res.statusText ? ` ${res.statusText}` : ''})`;
}
