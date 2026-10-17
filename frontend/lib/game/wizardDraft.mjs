/**
 * LDVELH - Creation wizard draft (format)
 * What is saved while a world is being created, whatever the store:
 * { version, step, form, open, savedAt }. `open` means the wizard was on screen,
 * so a reload goes straight back to it.
 */

import { INITIAL_WIZARD_FORM, WIZARD_STEPS } from './wizardForm.mjs';

// Bump when the form shape changes: older drafts are then ignored.
export const DRAFT_VERSION = 1;

const FORM_KEYS = Object.keys(INITIAL_WIZARD_FORM);

export function makeDraft({ step, form }, { open = true, now = Date.now() } = {}) {
	return { version: DRAFT_VERSION, step, form, open, savedAt: now };
}

/** A stored value back to a draft, or null when it is missing, foreign or outdated. */
export function parseDraft(value) {
	if (!isObject(value) || value.version !== DRAFT_VERSION) return null;
	const { step, form, open, savedAt } = value;
	if (!Number.isInteger(step) || step < 0 || step >= WIZARD_STEPS.length) return null;
	if (!isObject(form) || !FORM_KEYS.every(k => k in form)) return null;
	return { version: DRAFT_VERSION, step, form, open: open === true, savedAt: Number(savedAt) || 0 };
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
