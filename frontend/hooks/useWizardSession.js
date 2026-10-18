'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { attachDraft, draftParams, isBlankForm, makeDraft } from '../lib/game/wizardDraft.mjs';
import { INITIAL_WIZARD_FORM, WIZARD_STEPS } from '../lib/game/wizardForm.mjs';

/**
 * Lifecycle of a world being created, over a draft store (lib/game/draftStores.mjs):
 * the draft is saved on every change, offered in the game list, reopened after a
 * reload, attached to the game once it is created, and dropped once its world is
 * created (#88): until then a failed generation can be retried with the same
 * parameters, or edited in the wizard. One draft at a time: a new creation replaces
 * the previous draft at its first change, not before.
 *
 * @param {Object} deps
 * @param {Object} deps.store - { load, save, clear }
 * @param {Function} deps.openWizard - shows the wizard (clean game state)
 * @param {Function} deps.closeWizard - back to the game list
 * @param {Function} deps.completeWizard - (data, { gameId, onCreated }) creates the game
 *   (or reuses `gameId`), calls onCreated(id), then starts the world generation
 */
export function useWizardSession({ store, openWizard, closeWizard, completeWizard }) {
	const [loaded, setLoaded] = useState(false);
	const [resumable, setResumable] = useState(null); // draft offered in the game list (no game yet)
	const [attached, setAttached] = useState(null); // draft of a game whose world is not created yet
	const [session, setSession] = useState({ key: 0, initial: null }); // what the open wizard starts from
	const lastDraft = useRef(null);
	const ownsDraft = useRef(false); // the open wizard's form is the stored draft
	const editedGame = useRef(null); // game whose parameters the open wizard edits (null: a new game)

	// The stored draft as the screens see it (not on every keystroke: see save).
	const publish = useCallback((draft) => {
		lastDraft.current = draft;
		setResumable(draft && !draft.gameId ? draft : null);
		setAttached(draft?.gameId ? draft : null);
	}, []);

	useEffect(() => {
		let cancelled = false;
		setLoaded(false);
		store.load().then(draft => {
			if (cancelled) return;
			publish(draft);
			setLoaded(true);
		});
		return () => { cancelled = true; };
	}, [store, publish]);

	const begin = useCallback((initial) => {
		ownsDraft.current = !!initial;
		editedGame.current = initial?.gameId || null;
		setSession(s => ({ key: s.key + 1, initial }));
		openWizard();
	}, [openWizard]);

	const discard = useCallback(() => {
		publish(null);
		store.clear();
	}, [store, publish]);

	const startNew = useCallback(() => begin(null), [begin]);

	const resume = useCallback(() => begin(lastDraft.current), [begin]);

	/** Reopen the wizard on the parameters of `gameId` (world not created yet). */
	const edit = useCallback((gameId) => {
		if (lastDraft.current?.gameId === gameId) begin(lastDraft.current);
	}, [begin]);

	// The wizard was on screen when the page was reloaded: go straight back to it.
	const reopened = useRef(false);
	useEffect(() => {
		if (loaded && !reopened.current && (resumable || attached)?.open) {
			reopened.current = true;
			resume();
		}
	}, [loaded, resumable, attached, resume]);

	/** Wizard snapshot ({ step, form }) on every change. */
	const save = useCallback((snapshot) => {
		if (isBlankForm(snapshot.form)) {
			// Emptied (undo back to the start): no draft. A new, untouched wizard keeps the previous one.
			if (ownsDraft.current) discard();
			ownsDraft.current = false;
			return;
		}
		const replaced = lastDraft.current;
		const previous = ownsDraft.current ? replaced : null;
		ownsDraft.current = true;
		lastDraft.current = makeDraft(snapshot, {
			gameId: editedGame.current,
			submitted: previous?.gameId === editedGame.current ? previous?.submitted : null,
		});
		store.save(lastDraft.current);
		// A new creation replaced the draft of a game: that game falls back to the server's copy.
		if (replaced?.gameId && replaced.gameId !== editedGame.current) setAttached(null);
	}, [store, discard]);

	/** Leave the wizard: the draft stays, offered in the game list. */
	const cancel = useCallback(() => {
		if (lastDraft.current) {
			lastDraft.current = { ...lastDraft.current, open: false };
			store.save(lastDraft.current);
		}
		publish(lastDraft.current);
		closeWizard();
	}, [store, closeWizard, publish]);

	const complete = useCallback((data) => {
		// An untouched wizard has no draft of its own: its form is the empty one.
		const own = ownsDraft.current && lastDraft.current
			? lastDraft.current
			: makeDraft({ step: WIZARD_STEPS.length - 1, form: INITIAL_WIZARD_FORM });
		const onCreated = (gameId) => {
			const draft = attachDraft(own, gameId, data);
			store.save(draft);
			publish(draft);
		};
		return completeWizard(data, { gameId: editedGame.current, onCreated });
	}, [completeWizard, store, publish]);

	/** The world of `gameId` exists: its draft is done. */
	const worldCreated = useCallback((gameId) => {
		if (lastDraft.current?.gameId === gameId) discard();
	}, [discard]);

	return {
		resumable,
		startNew,
		resume,
		discard,
		edit,
		worldCreated,
		/** Parameters last sent for `gameId`, kept in this browser, or null. */
		paramsFor: (gameId) => draftParams(attached, gameId),
		// Remount key and props of the wizard (a new key per creation started or resumed)
		wizardKey: session.key,
		wizard: { initialDraft: session.initial, onSnapshot: save, onCancel: cancel, onComplete: complete },
	};
}
