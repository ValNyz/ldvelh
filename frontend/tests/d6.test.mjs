import { test } from 'node:test';
import assert from 'node:assert/strict';

import { d6SkillsForSubmit, formatDice, parseDice } from '../lib/game/d6.mjs';

test('dice codes round-trip through pips', () => {
	assert.equal(parseDice('3D+1'), 10);
	assert.equal(parseDice('2D'), 6);
	assert.equal(parseDice('', 6), 6);
	assert.equal(parseDice('n/a', 6), 6);
	assert.equal(formatDice(10), '3D+1');
	assert.equal(formatDice(6), '2D');
});

test('skills are sent as full codes with their attribute', () => {
	const byAttr = { 'Dextérité': ['Esquive', 'Bagarre'], 'Technique': ['Piratage'] };
	const out = d6SkillsForSubmit(
		{ Esquive: '1D+1', Piratage: '2D', Bagarre: '0D', Arcanes: '2D' },
		{ 'Dextérité': '3D+2' },
		byAttr,
	);
	assert.deepEqual(out, [
		{ attribute: 'Dextérité', name: 'Esquive', dice_value: '5D' },   // 3D+2 + 1D+1
		{ attribute: 'Technique', name: 'Piratage', dice_value: '4D' },  // default 2D + 2D
	]);
});
