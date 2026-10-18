'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { attachDraft, isBlankForm, makeDraft } from '../lib/game/wizardDraft.mjs';
import { INITIAL_WIZARD_FORM, WIZARD_STEPS } from '../lib/game/wizardForm.mjs';
import { formFromParams } from '../lib/game/wizardParams.mjs';

/**
 * Lifecycle of the worlds being created, over a draft store (lib/game/draftStores.mjs).
 *
 * - The world not created yet (no game): its draft is saved on every change, offered in
 *   the game list, reopened after a reload. One such draft at a time: a new creation
 *   replaces it at its first change, not before.
 * - Once its game exists, the draft moves under the game's id (#88), one per unfinished
 *   game, so another creation never overwrites it. It is dropped when the world exists
 *   or the game is deleted. Until then a failed generation can be retried with the same
 *   parameters, or edited in the wizard (from the server's parameters when this browser
 *   has no draft).
 *
 * @param {Object} deps
 * @param {Object} deps.store - { load(gameId?), save(draft), clear(gameId?), gameIds() }
 * @param {Function} deps.openWizard - shows the wizard (clean game state)
 * @param {Function} deps.closeWizard - back to the game list
 * @param {Function} deps.completeWizard - (data, { gameId, onCreated }) creates the game
 *   (or reuses `gameId`), calls onCreated(id), then starts the world generation
 */
export function useWizardSession({ store, openWizard, closeWizard, completeWizard }) {
	const [loaded, setLoaded] = useState(false);
	const [resumable, setResumable] = useState(null); // draft offered in the game list (no game yet)
	const [gameDrafts, setGameDrafts] = useState({}); // gameId -> draft of an unfinished game
	const [session, setSession] = useState({ key: 0, initial: null }); // what the open wizard starts from
	const lastDraft = useRef(null); // draft of the world not created yet
	const openDraft = useRef(null); // the open wizard's draft (lastDraft, or a game's)
	const ownsDraft = useRef(false); // the open wizard's form is a stored draft
	const editedGame = useRef(null); // game whose parameters the open wizard edits (null: a new game)
	const reopenOnLoad = useRef(null);

	const setGameDraft = useCallback((gameId, draft) => {
		setGameDrafts(all => {
			const next = { ...all };
			if (draft) next[gameId] = draft; else delete next[gameId];
			return next;
		});
	}, []);

	useEffect(() => {
		let cancelled = false;
		setLoaded(false);
		(async () => {
			const draft = await store.load();
			const ids = await store.gameIds();
			const drafts = {};
			for (const id of ids) {
				const d = await store.load(id);
				if (d) drafts[id] = d;
			}
			if (cancelled) return;
			lastDraft.current = draft;
			setResumable(draft);
			setGameDrafts(drafts);
			// The wizard was on screen when the page was reloaded: go straight back to it.
			reopenOnLoad.current = [draft, ...Object.values(drafts)].find(d => d?.open) || null;
			setLoaded(true);
		})();
		return () => { cancelled = true; };
	}, [store]);

	const begin = useCallback((initial) => {
		ownsDraft.current = !!initial;
		openDraft.current = initial;
		editedGame.current = initial?.gameId || null;
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

	/**
	 * Reopen the wizard on the parameters of `gameId` (world not created yet): this
	 * browser's draft, else the server's parameters (`serverParams`, camel case).
	 */
	const edit = useCallback((gameId, serverParams = null) => {
		const own = gameDrafts[gameId];
		if (own) return begin(own);
		if (!serverParams) return undefined;
		const form = formFromParams(serverParams);
		return begin(attachDraft(makeDraft({ step: WIZARD_STEPS.length - 1, form }), gameId, serverParams));
	}, [gameDrafts, begin]);

	useEffect(() => {
		const draft = reopenOnLoad.current;
		if (loaded && draft) {
			reopenOnLoad.current = null;
			begin(draft);
		}
	}, [loaded, begin]);

	/** Wizard snapshot ({ step, form }) on every change. */
	const save = useCallback((snapshot) => {
		const gameId = editedGame.current;
		if (isBlankForm(snapshot.form) && !gameId) {
			// Emptied (undo back to the start): no draft. A new, untouched wizard keeps the previous one.
			if (ownsDraft.current) discard();
			ownsDraft.current = false;
			return;
		}
		const previous = ownsDraft.current ? openDraft.current : null;
		ownsDraft.current = true;
		const draft = makeDraft(snapshot, { gameId, submitted: previous?.submitted });
		openDraft.current = draft;
		if (!gameId) lastDraft.current = draft;
		store.save(draft); // under the game's key when editing a game: the new-world draft is untouched
	}, [store, discard]);

	/** Leave the wizard: the draft stays, offered in the game list (or on its game). */
	const cancel = useCallback(() => {
		const draft = openDraft.current && ownsDraft.current ? { ...openDraft.current, open: false } : null;
		if (draft) store.save(draft);
		if (draft?.gameId) {
			setGameDraft(draft.gameId, draft);
		} else {
			if (draft) lastDraft.current = draft;
			setResumable(lastDraft.current);
		}
		closeWizard();
	}, [store, closeWizard, setGameDraft]);

	const complete = useCallback((data) => {
		// An untouched wizard has no draft of its own: its form is the empty one.
		const own = ownsDraft.current && openDraft.current
			? openDraft.current
			: makeDraft({ step: WIZARD_STEPS.length - 1, form: INITIAL_WIZARD_FORM });
		const wasNew = !editedGame.current;
		const onCreated = (gameId) => {
			const draft = attachDraft(own, gameId, data);
			store.save(draft); // moves under the game's key
			setGameDraft(gameId, draft);
			if (wasNew && ownsDraft.current) discard(); // no longer a world without a game
		};
		return completeWizard(data, { gameId: editedGame.current, onCreated });
	}, [completeWizard, store, setGameDraft, discard]);

	/** `gameId` no longer needs its draft: its world exists, or the game was deleted. */
	const forget = useCallback((gameId) => {
		store.clear(gameId);
		setGameDraft(gameId, null);
	}, [store, setGameDraft]);

	/** Drop the stored drafts of games missing from `games` (deleted elsewhere). */
	const prune = useCallback(async (games) => {
		const alive = new Set(games.map(g => g.id));
		for (const id of await store.gameIds()) if (!alive.has(id)) forget(id);
	}, [store, forget]);

	return {
		resumable,
		startNew,
		resume,
		discard,
		edit,
		forget,
		prune,
		/** Parameters last sent for `gameId` from this browser, or null. */
		paramsFor: (gameId) => gameDrafts[gameId]?.submitted || null,
		// Remount key and props of the wizard (a new key per creation started or resumed)
		wizardKey: session.key,
		wizard: { initialDraft: session.initial, onSnapshot: save, onCancel: cancel, onComplete: complete },
	};
}
