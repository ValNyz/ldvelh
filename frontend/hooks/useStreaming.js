'use client';

import { useRef, useCallback, useState } from 'react';
import { apiUrl, getAuthHeaders } from '../lib/api';

/**
 * Hook pour gérer le streaming SSE
 */
export function useStreaming({ onChunk, onProgress, onExtracting, onDone, onSaved, onError, onRollResult, onRollPending, onStatus }) {
	const abortControllerRef = useRef(null);
	const [rawJson, setRawJson] = useState('');

	const startStream = useCallback(async (url, body) => {
		// Cancel any in-flight stream before starting a new one
		if (abortControllerRef.current) {
			abortControllerRef.current.abort();
		}
		abortControllerRef.current = new AbortController();
		let fullJson = '';
		setRawJson('');

		try {
			// Utiliser apiUrl() pour construire l'URL complète du backend
			const fullUrl = apiUrl(url);

			const res = await fetch(fullUrl, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
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

						switch (data.type) {
							case 'chunk':
								onChunk?.(data.content);
								break;

							case 'progress':
								fullJson = data.rawJson || fullJson;
								setRawJson(fullJson);
								onProgress?.(fullJson);
								break;

							case 'extracting':
								onExtracting?.(data.displayText);
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

							case 'roll_result':
								onRollResult?.(data.roll);
								break;

							case 'roll_pending':
								onRollPending?.(data);
								break;

							case 'status':
								onStatus?.(data);
								break;

							case 'warning':
								console.warn('[Stream] Warning:', data.message);
								break;

							default:
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
	}, [onChunk, onProgress, onExtracting, onDone, onSaved, onError, onRollResult, onRollPending, onStatus]);

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
