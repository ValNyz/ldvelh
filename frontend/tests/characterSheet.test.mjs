import { test } from 'node:test';
import assert from 'node:assert/strict';

import { d6SkillsByAttribute, fateSkillPyramid, formatFateLevel } from '../lib/game/characterSheet.mjs';

test('Fate skills form a pyramid, highest level first', () => {
	const pyramid = fateSkillPyramid([
		{ name: 'Combat', level: 2, label: 'Correct' },
		{ name: 'Athlétisme', level: 4, label: 'Excellent' },
		{ name: 'Discrétion', level: 2, label: 'Correct' },
		{ name: 'Contacts', level: 1, label: 'Moyen' },
	]);
	assert.deepEqual(pyramid, [
		{ level: 4, label: 'Excellent', skills: ['Athlétisme'] },
		{ level: 2, label: 'Correct', skills: ['Combat', 'Discrétion'] },
		{ level: 1, label: 'Moyen', skills: ['Contacts'] },
	]);
	assert.deepEqual(fateSkillPyramid(), []);
});

test('Fate levels are signed', () => {
	assert.equal(formatFateLevel(3), '+3');
	assert.equal(formatFateLevel(0), '0');
	assert.equal(formatFateLevel(-1), '-1');
});

test('D6 skills sit under their attribute, accents ignored', () => {
	const { rows, others } = d6SkillsByAttribute(
		{ 'Dextérité': '3D', 'Mécanique': '2D+1' },
		[
			{ attribute: 'Dexterite', name: 'Blaster', dice_value: '4D' },
			{ attribute: 'Mécanique', name: 'Pilotage', dice_value: '3D+2' },
			{ attribute: 'Magie', name: 'Sort', dice_value: '1D' },
		],
	);
	assert.deepEqual(rows.map(r => [r.name, r.dice, r.skills.map(s => s.name)]), [
		['Dextérité', '3D', ['Blaster']],
		['Mécanique', '2D+1', ['Pilotage']],
	]);
	assert.deepEqual(others.map(s => s.name), ['Sort']);
});
