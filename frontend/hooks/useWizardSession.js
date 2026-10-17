'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { isBlankForm, makeDraft } from '../lib/game/wizardDraft.mjs';

/**
 * Lifecycle of a world being created, over a draft store (lib/game/draftStores.mjs):
 * the draft is saved on every change, offered in the game list, reopened after a
 * reload, and dropped once the game is created. One draft at a time: a new
 * creation replaces the previous draft at its first change, not before.
 *
 * @param {Object} deps
 * @param {Object} deps.store - { load, save, clear }
 * @param {Function} deps.openWizard - shows the wizard (clean game state)
 * @param {Function} deps.closeWizard - back to the game list
 * @param {Function} deps.completeWizard - (data, { onCreated }) creates the game
 */
export function useWizardSession({ store, openWizard, closeWizard, completeWizard }) {
	const [loaded, setLoaded] = useState(false);
	const [resumable, setResumable] = useState(null); // draft offered in the game list
	const [session, setSession] = useState({ key: 0, initial: null }); // what the open wizard starts from
	const lastDraft = useRef(null);
	const ownsDraft = useRef(false); // the open wizard's form is the stored draft

	useEffect(() => {
		let cancelled = false;
		setLoaded(false);
		store.load().then(draft => {
			if (cancelled) return;
			lastDraft.current = draft;
			setResumable(draft);
			setLoaded(true);
		});
		return () => { cancelled = true; };
	}, [store]);

	const begin = useCallback((initial) => {
		ownsDraft.current = !!initial;
		setSession(s => ({ key: s.key + 1, initial }));
		openWizard();
	}, [openWizard]);

	const discard = useCallback(() => {
		lastDraft.current = null;
		setResumable(null);
		store.clear();
	}, [store]);

	const startNew = useCallback(() => begin(null), [begin]);

	const resume = useCallback(() => begin(lastDraft.current), [begin]);

	// The wizard was on screen when the page was reloaded: go straight back to it.
	const reopened = useRef(false);
	useEffect(() => {
		if (loaded && !reopened.current && resumable?.open) {
			reopened.current = true;
			resume();
		}
	}, [loaded, resumable, resume]);

	/** Wizard snapshot ({ step, form }) on every change. */
	const save = useCallback((snapshot) => {
		if (isBlankForm(snapshot.form)) {
			// Emptied (undo back to the start): no draft. A new, untouched wizard keeps the previous one.
			if (ownsDraft.current) discard();
			ownsDraft.current = false;
			return;
		}
		ownsDraft.current = true;
		lastDraft.current = makeDraft(snapshot);
		store.save(lastDraft.current);
	}, [store, discard]);

	/** Leave the wizard: the draft stays, offered in the game list. */
	const cancel = useCallback(() => {
		if (lastDraft.current) {
			lastDraft.current = { ...lastDraft.current, open: false };
			store.save(lastDraft.current);
		}
		setResumable(lastDraft.current);
		closeWizard();
	}, [store, closeWizard]);

	const complete = useCallback(
		(data) => completeWizard(data, { onCreated: discard }),
		[completeWizard, discard],
	);

	return {
		resumable,
		startNew,
		resume,
		discard,
		// Remount key and props of the wizard (a new key per creation started or resumed)
		wizardKey: session.key,
		wizard: { initialDraft: session.initial, onSnapshot: save, onCancel: cancel, onComplete: complete },
	};
}
