/**
 * LDVELH - Creation wizard draft (format)
 * What is saved while a world is being created, whatever the store:
 * { version, step, form, open, savedAt, gameId?, submitted? }. `open` means the wizard
 * was on screen, so a reload goes straight back to it. Once the game exists, `gameId`
 * names it and `submitted` holds the parameters sent with __INIT__ ({ engine,
 * worldConfig, characterData, manualEntities }): the draft is kept until the world is
 * created, so a failed generation can be retried or edited (#88).
 */

import { INITIAL_WIZARD_FORM, WIZARD_STEPS } from './wizardForm.mjs';

// Bump when the form shape changes: older drafts are then ignored.
export const DRAFT_VERSION = 1;

const FORM_KEYS = Object.keys(INITIAL_WIZARD_FORM);

export function makeDraft({ step, form }, { open = true, now = Date.now(), gameId = null, submitted = null } = {}) {
	return { version: DRAFT_VERSION, step, form, open, savedAt: now, ...gameFields(gameId, submitted) };
}

/** The draft of a game whose world is not created yet. */
export function attachDraft(draft, gameId, submitted) {
	return { ...draft, open: false, ...gameFields(gameId, submitted) };
}

function gameFields(gameId, submitted) {
	if (typeof gameId !== 'string' || !gameId) return {};
	return isObject(submitted) ? { gameId, submitted } : { gameId };
}

/** A stored value back to a draft, or null when it is missing, foreign or outdated. */
export function parseDraft(value) {
	if (!isObject(value) || value.version !== DRAFT_VERSION) return null;
	const { step, form, open, savedAt, gameId, submitted } = value;
	if (!Number.isInteger(step) || step < 0 || step >= WIZARD_STEPS.length) return null;
	if (!isObject(form) || !FORM_KEYS.every(k => k in form)) return null;
	return {
		version: DRAFT_VERSION, step, form, open: open === true, savedAt: Number(savedAt) || 0,
		...gameFields(gameId, submitted),
	};
}

/** Nothing worth keeping: the form is still the empty one. */
export function isBlankForm(form) {
	return JSON.stringify(form) === JSON.stringify(INITIAL_WIZARD_FORM);
}

/** One line for the game list: the lore, else the hero's name, else nothing. */
export function draftTitle(draft) {
	const lore = draft.form.worldConfig?.lore?.trim();
	if (lore) return lore.length > 90 ? `${lore.slice(0, 90).trimEnd()}…` : lore;
	return draft.form.characterData?.name?.trim() || '';
}

function isObject(v) {
	return v !== null && typeof v === 'object' && !Array.isArray(v);
}
