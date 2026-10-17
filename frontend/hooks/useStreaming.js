'use client';

import { useRef, useCallback, useState } from 'react';
import { apiUrl, getAuthHeaders, refreshSession } from '../lib/api';
import { runChatStream } from '../lib/chatStream.mjs';

/**
 * /chat SSE stream for React: cancellation and dispatch of each event to its
 * callback. The stream itself (HTTP errors, 401 refresh, terminal event
 * guarantee) lives in lib/chatStream.mjs.
 */
export function useStreaming({
	onChunk, onProgress, onExtracting, onDone, onSaved, onSaveUnconfirmed, onError,
	onRollResult, onRollPending, onStatus, onWarning,
}) {
	const abortControllerRef = useRef(null);
	const [rawJson, setRawJson] = useState('');

	const startStream = useCallback(async (url, body) => {
		// Cancel any in-flight stream before starting a new one
		abortControllerRef.current?.abort();
		const controller = new AbortController();
		abortControllerRef.current = controller;
		let fullJson = '';
		setRawJson('');

		const dispatch = (data) => {
			switch (data.type) {
				case 'chunk': onChunk?.(data.content); break;
				case 'progress':
					fullJson = data.rawJson || fullJson;
					setRawJson(fullJson);
					onProgress?.(fullJson);
					break;
				case 'extracting': onExtracting?.(data.displayText); break;
				case 'done': onDone?.(data.displayText, data.state); break;
				case 'saved': onSaved?.(); break;
				case 'save_unconfirmed': onSaveUnconfirmed?.(); break;
				case 'error': onError?.(data.error, data.details, { status: data.status, interrupted: !!data.interrupted, recoverable: data.recoverable, code: data.code }); break;
				case 'roll_result': onRollResult?.(data.roll); break;
				case 'roll_pending': onRollPending?.(data); break;
				case 'status': onStatus?.(data); break;
				case 'warning':
					console.warn('[Stream] Warning:', data.message);
					onWarning?.(data.message);
					break;
				default: break;
			}
		};

		try {
			const result = await runChatStream({
				url: apiUrl(url),
				body,
				signal: controller.signal,
				onEvent: dispatch,
				getHeaders: getAuthHeaders,
				refreshSession,
			});
			return { ...result, fullJson };
		} finally {
			if (abortControllerRef.current === controller) abortControllerRef.current = null;
		}
	}, [onChunk, onProgress, onExtracting, onDone, onSaved, onSaveUnconfirmed, onError, onRollResult, onRollPending, onStatus, onWarning]);

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
