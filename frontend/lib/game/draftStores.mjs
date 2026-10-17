/**
 * LDVELH - Wizard draft stores
 * A store is { load(): Promise<draft|null>, save(draft): Promise, clear(): Promise }.
 * The interface is async so a server-backed store can replace this one without
 * changing its callers.
 */

import { parseDraft } from './wizardDraft.mjs';

export const draftKey = (userId) => `ldvelh.wizardDraft.${userId}`;

/**
 * Draft kept in the browser (localStorage), per user. Storage can be missing or
 * throw (private window, blocked site data): the wizard then works without a draft.
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
	return {
		load: async () => attempt(s => parseDraft(JSON.parse(s.getItem(key))), null),
		save: async (draft) => attempt(s => s.setItem(key, JSON.stringify(draft))),
		clear: async () => attempt(s => s.removeItem(key)),
	};
}
