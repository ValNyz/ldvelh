import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { INVALID_PC_NAME, protagonistNameError } from '../lib/game/wizardForm.mjs';

// The same cases drive the backend test (tests/test_protagonist_ref.py), so the two rules cannot drift.
const CASES = JSON.parse(readFileSync(new URL('./fixtures/protagonist-names.json', import.meta.url), 'utf8'));

test('the inline message is the API message', () => {
	assert.equal(INVALID_PC_NAME, CASES.message);
});

test('a blank or ordinary protagonist name passes', () => {
	for (const name of [undefined, null, ...CASES.accepted])
		assert.equal(protagonistNameError(name), null, JSON.stringify(name));
});

test('< > and the reserved reference are refused with the French message of the API', () => {
	for (const name of CASES.refused)
		assert.equal(protagonistNameError(name), INVALID_PC_NAME, JSON.stringify(name));
});
