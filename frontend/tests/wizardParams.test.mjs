import { test } from 'node:test';
import assert from 'node:assert/strict';

import { formFromParams, paramsFromServer } from '../lib/game/wizardParams.mjs';
import { INITIAL_WIZARD_FORM } from '../lib/game/wizardForm.mjs';

test('#88: server parameters (snake case) become the __INIT__ parameters (camel case)', () => {
	assert.deepEqual(paramsFromServer({
		engine: 'fate_core', world_config: { genre: 'cyberpunk' }, character_data: null, manual_entities: { npcs: [] },
	}), { engine: 'fate_core', worldConfig: { genre: 'cyberpunk' }, characterData: null, manualEntities: { npcs: [] } });
	assert.equal(paramsFromServer(null), null);
	assert.equal(paramsFromServer({ engine: 'none', world_config: null, character_data: null, manual_entities: null }), null);
});

test('#88: sent parameters back to a wizard form (Fate, entities, missing parts)', () => {
	const form = formFromParams({
		engine: 'fate_core',
		worldConfig: { genre: 'cyberpunk', difficulty: 'hard', duration: 'short', hardcore: true },
		characterData: { name: 'Kira', aspects: { high_concept: 'Pilote', trouble: 'Dettes', other: ['', '', ''] }, skills: { Combat: 4 } },
		manualEntities: { npcs: [{ name: 'Varek', description: 'Contrebandier' }] },
	});
	assert.deepEqual(form, {
		engine: 'fate_core',
		worldConfig: { genre: 'cyberpunk', difficulty: 'hard', duration: 'short', hardcore: true, lore: '' },
		characterData: { name: 'Kira', aspects: { high_concept: 'Pilote', trouble: 'Dettes', other: ['', '', ''] }, skills: { Combat: 4 } },
		manualEntities: { npcs: [{ name: 'Varek', description: 'Contrebandier' }] },
	});
	assert.deepEqual(formFromParams({ engine: 'none', worldConfig: null, characterData: null, manualEntities: null }),
		{ ...INITIAL_WIZARD_FORM, worldConfig: { ...INITIAL_WIZARD_FORM.worldConfig }, characterData: {}, manualEntities: {} });
});

test('#88: D6 skills sent as full codes go back to the dice added over their attribute', () => {
	const form = formFromParams({
		engine: 'd6', worldConfig: { genre: 'sci_fi' },
		characterData: {
			name: 'Kira', attributes: { 'Dextérité': '3D', 'Savoir': '2D' },
			skills: [
				{ attribute: 'Dextérité', name: 'Esquive', dice_value: '4D+1' },
				{ attribute: 'Savoir', name: 'Bureaucratie', dice_value: '3D' },
				{ attribute: 'Inconnu', name: 'Rien', dice_value: '1D' },
			],
		},
		manualEntities: null,
	});
	assert.deepEqual(form.characterData.skills, { Esquive: '1D+1', Bureaucratie: '1D' });
	assert.deepEqual(form.characterData.attributes, { 'Dextérité': '3D', 'Savoir': '2D' });
});
