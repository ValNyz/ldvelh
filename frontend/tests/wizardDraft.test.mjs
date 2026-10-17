import { test } from 'node:test';
import assert from 'node:assert/strict';

import { DRAFT_VERSION, draftTitle, isBlankForm, makeDraft, parseDraft } from '../lib/game/wizardDraft.mjs';
import { draftKey, localDraftStore } from '../lib/game/draftStores.mjs';
import { INITIAL_WIZARD_FORM } from '../lib/game/wizardForm.mjs';

const FORM = { ...INITIAL_WIZARD_FORM, worldConfig: { ...INITIAL_WIZARD_FORM.worldConfig, lore: 'Néo-Lyon sous la pluie' } };

function memoryStorage() {
	const data = new Map();
	return {
		getItem: k => (data.has(k) ? data.get(k) : null),
		setItem: (k, v) => data.set(k, String(v)),
		removeItem: k => data.delete(k),
	};
}

test('a draft round-trips through parseDraft', () => {
	const draft = makeDraft({ step: 1, form: FORM }, { now: 1000 });
	assert.deepEqual(parseDraft(JSON.parse(JSON.stringify(draft))),
		{ version: DRAFT_VERSION, step: 1, form: FORM, open: true, savedAt: 1000 });
});

test('foreign, outdated or broken values are not drafts', () => {
	const ok = makeDraft({ step: 0, form: FORM });
	assert.equal(parseDraft(null), null);
	assert.equal(parseDraft('x'), null);
	assert.equal(parseDraft({ ...ok, version: DRAFT_VERSION + 1 }), null);
	assert.equal(parseDraft({ ...ok, step: 3 }), null);
	assert.equal(parseDraft({ ...ok, form: { engine: 'd6' } }), null);
});

test('the empty form is blank, any edit is not', () => {
	assert.equal(isBlankForm(INITIAL_WIZARD_FORM), true);
	assert.equal(isBlankForm(FORM), false);
	assert.equal(isBlankForm({ ...INITIAL_WIZARD_FORM, engine: 'd6' }), false);
});

test('draftTitle: the lore, else the hero, else nothing', () => {
	assert.equal(draftTitle(makeDraft({ step: 0, form: FORM })), 'Néo-Lyon sous la pluie');
	const hero = { ...INITIAL_WIZARD_FORM, characterData: { name: 'Nyx' } };
	assert.equal(draftTitle(makeDraft({ step: 2, form: hero })), 'Nyx');
	assert.equal(draftTitle(makeDraft({ step: 0, form: INITIAL_WIZARD_FORM })), '');
	const long = { ...FORM, worldConfig: { ...FORM.worldConfig, lore: 'a'.repeat(200) } };
	assert.ok(draftTitle(makeDraft({ step: 0, form: long })).endsWith('…'));
});

test('local store saves, loads and clears per key', async () => {
	const storage = memoryStorage();
	const store = localDraftStore(() => storage, draftKey('u1'));
	assert.equal(await store.load(), null);
	const draft = makeDraft({ step: 2, form: FORM });
	await store.save(draft);
	assert.deepEqual(await store.load(), draft);
	assert.equal(await localDraftStore(() => storage, draftKey('u2')).load(), null, 'other user');
	await store.clear();
	assert.equal(await store.load(), null);
});

test('local store survives missing or throwing storage', async () => {
	const throwing = { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); }, removeItem() {} };
	for (const getStorage of [() => null, () => throwing, () => { throw new Error('denied'); }]) {
		const store = localDraftStore(getStorage, 'k');
		assert.equal(await store.load(), null);
		await store.save(makeDraft({ step: 0, form: FORM }));
		await store.clear();
	}
	const corrupt = memoryStorage();
	corrupt.setItem('k', '{not json');
	assert.equal(await localDraftStore(() => corrupt, 'k').load(), null);
});
