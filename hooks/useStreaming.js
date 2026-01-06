import { useRef, useCallback } from 'react';

/**
 * Extraction du narratif depuis JSON streamé
 */
function extractNarratif(jsonStr) {
	const m = jsonStr.match(/"narratif"\s*:\s*"/);
	if (!m) return null;
	let narratif = '', i = m.index + m[0].length;
	while (i < jsonStr.length) {
		const c = jsonStr[i];
		if (c === '\\' && i + 1 < jsonStr.length) {
			const n = jsonStr[i + 1];
			if (n === 'n') { narratif += '\n'; i += 2; }
			else if (n === '"') { narratif += '"'; i += 2; }
			else if (n === '\\') { narratif += '\\'; i += 2; }
			else if (n === 't') { narratif += '\t'; i += 2; }
			else if (n === 'r') { narratif += '\r'; i += 2; }
			else { narratif += c; i++; }
		} else if (c === '"') { break; }
		else { narratif += c; i++; }
	}
	return narratif || null;
}

function extractHeure(jsonStr) {
	const m = jsonStr.match(/"heure"\s*:\s*"([^"]+)"/);
	return m ? m[1] : null;
}

function extractChoix(jsonStr) {
	const match = jsonStr.match(/"choix"\s*:\s*\[([\s\S]*?)\]/);
	if (!match) return null;
	try {
		const arr = JSON.parse(`[${match[1]}]`);
		return arr.length > 0 ? arr : null;
	} catch (e) {
		return null;
	}
}

/**
 * Construit le contenu à afficher depuis le JSON streamé
 */
export function extractDisplayContent(content) {
	const trimmed = content.trim();
	if (trimmed.startsWith('{')) {
		const narratif = extractNarratif(content);
		const heure = extractHeure(content);
		const choix = extractChoix(content);
		if (narratif) {
			let display = narratif.replace(/^\[?\d{2}h\d{2}\]?\s*[-–—:]?\s*/i, '');
			if (heure) display = `[${heure}] ${display}`;
			if (choix?.length > 0) {
				display += '\n\n' + choix.map((c, i) => `${i + 1}. ${c}`).join('\n');
			}
			return display;
		}
		return null;
	}
	return content || null;
}

/**
 * Hook pour gérer le streaming SSE
 */
export function useStreaming({ onChunk, onDone, onSaved, onError }) {
	const abortControllerRef = useRef(null);

	const startStream = useCallback(async (url, body) => {
		abortControllerRef.current = new AbortController();
		let fullJson = '';

		try {
			const res = await fetch(url, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(body),
				signal: abortControllerRef.current.signal
			});

			if (!res.headers.get('content-type')?.includes('text/event-stream')) {
				// Réponse non-streaming
				const data = await res.json();
				if (data.error) {
					onError?.(data.error, data.details);
					return { success: false };
				}
				onDone?.(data.displayText || data.content, data.state);
				return { success: true, data };
			}

			// Streaming SSE
			const reader = res.body.getReader();
			const decoder = new TextDecoder();

			while (true) {
				const { done, value } = await reader.read();
				if (done) break;

				const text = decoder.decode(value, { stream: true });

				for (const line of text.split('\n')) {
					if (!line.startsWith('data: ')) continue;

					try {
						const data = JSON.parse(line.slice(6));

						switch (data.type) {
							case 'chunk':
								// On l'affiche directement (remplace le contenu précédent)
								onChunk?.(data.content, fullJson);
								break;

							case 'done':
								// Le displayText final remplace tout
								onDone?.(data.displayText || fullJson, data.state);
								break;

							case 'saved':
								onSaved?.();
								break;

							case 'error':
								onError?.(data.error, data.details);
								break;
						}
					} catch (e) {
						// Ignorer les lignes mal formées
					}
				}
			}

			return { success: true, fullJson };

		} catch (e) {
			if (e.name === 'AbortError') {
				return { success: false, aborted: true, partialContent: fullJson };
			}
			onError?.(e.message);
			return { success: false, error: e };
		} finally {
			abortControllerRef.current = null;
		}
	}, [onChunk, onDone, onSaved, onError]);

	const cancel = useCallback(() => {
		if (abortControllerRef.current) {
			abortControllerRef.current.abort();
			abortControllerRef.current = null;
			return true;
		}
		return false;
	}, []);

	const isStreaming = useCallback(() => {
		return abortControllerRef.current !== null;
	}, []);

	return { startStream, cancel, isStreaming };
}
