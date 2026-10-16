'use client';

import { useState, useCallback } from 'react';
import { changeKey, createHistory, push, redo, redoMeta, undo, undoMeta } from '../lib/game/formHistory.mjs';

/**
 * Form state with undo / redo (see lib/game/formHistory.mjs).
 * set(updater, { key, meta }): key defaults to the one field that changed, so
 * successive edits of one field merge; pass key: null to make the change its own entry (AI fill).
 */
export function useFormHistory(initial) {
	const [history, setHistory] = useState(() => createHistory(initial));

	const set = useCallback((updater, { key, meta = null } = {}) => {
		setHistory(prev => {
			const next = typeof updater === 'function' ? updater(prev.present) : updater;
			return push(prev, next, {
				key: key === undefined ? changeKey(prev.present, next) : key,
				meta,
			});
		});
	}, []);

	return {
		state: history.present,
		set,
		undo: useCallback(() => setHistory(undo), []),
		redo: useCallback(() => setHistory(redo), []),
		canUndo: history.past.length > 0,
		canRedo: history.future.length > 0,
		undoMeta: undoMeta(history),
		redoMeta: redoMeta(history),
	};
}
