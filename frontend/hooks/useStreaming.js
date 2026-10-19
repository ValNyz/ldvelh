'use client';

import { useRef, useCallback } from 'react';
import { apiUrl, getAuthHeaders, refreshSession } from '../lib/api';
import { runChatStream } from '../lib/chatStream.mjs';

/**
 * /chat SSE streams for React: cancellation and dispatch of each event to its
 * callback. The stream itself (HTTP errors, 401 refresh, terminal event
 * guarantee) lives in lib/chatStream.mjs.
 *
 * Streams are keyed (by game): one per key at a time, and streams of different
 * keys run side by side, so leaving a game never cuts its turn (#143).
 */
export function useStreaming() {
	const controllersRef = useRef(new Map()); // key -> AbortController

	/**
	 * @param {string} url
	 * @param {Object} body
	 * @param {Object} opts
	 * @param {*} [opts.key] - starting a stream cancels the in-flight one of the same key only;
	 *   callers without a key share the `null` slot (pass one to run streams side by side)
	 * @param {Object} opts.callbacks - { onChunk, onProgress, onExtracting, onDone, onSaved,
	 *   onSaveUnconfirmed, onError, onRollResult, onRollPending, onStatus, onWarning }
	 */
	const startStream = useCallback(async (url, body, { key = null, callbacks = {} } = {}) => {
		const controllers = controllersRef.current;
		controllers.get(key)?.abort();
		const controller = new AbortController();
		controllers.set(key, controller);
		let fullJson = '';
		const {
			onChunk, onProgress, onExtracting, onDone, onSaved, onSaveUnconfirmed, onError,
			onRollResult, onRollPending, onStatus, onWarning,
		} = callbacks;

		const dispatch = (data) => {
			switch (data.type) {
				case 'chunk': onChunk?.(data.content); break;
				case 'progress':
					fullJson = data.rawJson || fullJson;
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
			if (controllers.get(key) === controller) controllers.delete(key);
		}
	}, []);

	/** Cancels the in-flight stream of `key`; true when there was one. */
	const cancel = useCallback((key = null) => {
		const controller = controllersRef.current.get(key);
		if (!controller) return false;
		controller.abort();
		controllersRef.current.delete(key);
		return true;
	}, []);

	return { startStream, cancel };
}
