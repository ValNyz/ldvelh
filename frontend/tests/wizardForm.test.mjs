import { test } from 'node:test';
import assert from 'node:assert/strict';

import { INVALID_PC_NAME, protagonistNameError } from '../lib/game/wizardForm.mjs';

test('a blank or ordinary protagonist name passes', () => {
	for (const name of [undefined, null, '', '   ', 'Kira', ' Kira Voss ', "N'Diaye", 'Protagoniste'])
		assert.equal(protagonistNameError(name), null, JSON.stringify(name));
});

test('< > and the reserved reference are refused with the French message of the API', () => {
	for (const name of ['<prénom inventé>', 'Kira <x>', 'Kira>', 'PROTAGONIST', ' protagonist '])
		assert.equal(protagonistNameError(name), INVALID_PC_NAME, JSON.stringify(name));
	assert.match(INVALID_PC_NAME, /^Nom du protagoniste invalide/);
});
