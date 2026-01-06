import { useRef, useCallback } from 'react';

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
