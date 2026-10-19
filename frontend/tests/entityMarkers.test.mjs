import { test } from 'node:test';
import assert from 'node:assert/strict';

import { injectEntityMarkers } from '../lib/game/entityMarkers.mjs';

const map = {
	vergence: { name: 'Vergence' },
	'pater ondrev': { name: 'Pater Ondrev' },
	'élan': { name: 'Élan' },
};

test('a name inside a longer word is not tagged (#142)', () => {
	assert.equal(
		injectEntityMarkers('Avant la convergence, deux divergences.', map),
		'Avant la convergence, deux divergences.',
	);
});

test('accented letters count as word letters', () => {
	assert.equal(injectEntityMarkers('Un réélan soudain.', map), 'Un réélan soudain.');
	assert.equal(injectEntityMarkers("L'Élan repart.", map), "L'**Élan** repart.");
});

test('a whole-word name is tagged, case-insensitively, at every occurrence', () => {
	assert.equal(
		injectEntityMarkers('Vergence dort. À vergence, Pater Ondrev parle.', map),
		'**Vergence** dort. À **vergence**, **Pater Ondrev** parle.',
	);
});

test('an already bold name is left as is', () => {
	assert.equal(injectEntityMarkers('**Vergence** dort.', map), '**Vergence** dort.');
});

test('names shorter than 3 letters and empty maps are ignored', () => {
	assert.equal(injectEntityMarkers('Va à Io.', { io: { name: 'Io' } }), 'Va à Io.');
	assert.equal(injectEntityMarkers('Vergence.', {}), 'Vergence.');
});
