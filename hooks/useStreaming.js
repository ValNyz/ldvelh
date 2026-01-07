import { useRef, useCallback, useState } from 'react';

/**
 * Hook pour gérer le streaming SSE
 */
export function useStreaming({ onChunk, onProgress, onDone, onSaved, onError }) {
	const abortControllerRef = useRef(null);
	const [rawJson, setRawJson] = useState('');

	const startStream = useCallback(async (url, body) => {
		abortControllerRef.current = new AbortController();
		let fullJson = '';
		setRawJson('');

		try {
			const res = await fetch(url, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(body),
				signal: abortControllerRef.current.signal
			});

			if (!res.headers.get('content-type')?.includes('text/event-stream')) {
				const data = await res.json();
				if (data.error) {
					onError?.(data.error, data.details);
					return { success: false };
				}
				onDone?.(data.displayText || data.content, data.state);
				return { success: true, data };
			}

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
						console.log('[Stream] Event reçu:', data.type, '| keys:', Object.keys(data));

						switch (data.type) {
							case 'chunk':
								onChunk?.(data.content);
								break;

							case 'progress':
								fullJson = data.rawJson || fullJson;
								setRawJson(fullJson);
								onProgress?.(fullJson);
								break;

							case 'done':
								onDone?.(data.displayText, data.state);
								break;

							case 'saved':
								onSaved?.();
								break;

							case 'error':
								onError?.(data.error, data.details);
								break;

							case 'warning':
								console.warn('[Stream] Warning:', data.message);
								break;

							default:
								console.log('[Stream] Type inconnu:', data.type);
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
	}, [onChunk, onProgress, onDone, onSaved, onError]);

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

	return { startStream, cancel, isStreaming, rawJson };
}
