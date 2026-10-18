/**
 * LDVELH - Wizard draft stores
 * A store keeps the draft of the world being created (no game yet) and one draft per
 * game whose world is not created yet (#88):
 * { load(gameId?): Promise<draft|null>, save(draft): Promise, clear(gameId?): Promise,
 *   gameIds(): Promise<string[]> }. `save` files a draft under its own `gameId`.
 * The interface is async so a server-backed store can replace this one without
 * changing its callers.
 */

import { parseDraft } from './wizardDraft.mjs';

export const draftKey = (userId) => `ldvelh.wizardDraft.${userId}`;

/**
 * Drafts kept in the browser (localStorage), per user: the new world's under `key`, a
 * game's under `key.<gameId>`. Storage can be missing or throw (private window, blocked
 * site data): the wizard then works without a draft.
 * @param {() => Storage|null} getStorage
 * @param {string} key
 */
export function localDraftStore(getStorage, key) {
	const attempt = (fn, fallback = undefined) => {
		try {
			const storage = getStorage();
			return storage ? fn(storage) : fallback;
		} catch {
			return fallback;
		}
	};
	const keyOf = (gameId) => (gameId ? `${key}.${gameId}` : key);
	const prefix = `${key}.`;
	return {
		load: async (gameId = null) => attempt(s => parseDraft(JSON.parse(s.getItem(keyOf(gameId)))), null),
		save: async (draft) => attempt(s => s.setItem(keyOf(draft.gameId), JSON.stringify(draft))),
		clear: async (gameId = null) => attempt(s => s.removeItem(keyOf(gameId))),
		gameIds: async () => attempt(s => {
			const ids = [];
			for (let i = 0; i < s.length; i += 1) {
				const k = s.key(i);
				if (k?.startsWith(prefix)) ids.push(k.slice(prefix.length));
			}
			return ids;
		}, []),
	};
}
