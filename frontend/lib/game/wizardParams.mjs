/**
 * LDVELH - Wizard parameters (what __INIT__ sends) and back (#88)
 * The parameters of a game whose world is not created yet come from this browser's draft
 * or from the server (GET /games/{id} `init_params`). To edit them, they go back to a
 * wizard form: the inverse of the wizard's submit (WizardContainer handleNext).
 */

import { formatDice, parseDice } from './d6.mjs';
import { INITIAL_WIZARD_FORM } from './wizardForm.mjs';

/** GET /games/{id} `init_params` -> { engine, worldConfig, characterData, manualEntities }, or null. */
export function paramsFromServer(init) {
	if (!init?.world_config && !init?.character_data && !init?.manual_entities) return null;
	return {
		engine: init.engine,
		worldConfig: init.world_config,
		characterData: init.character_data,
		manualEntities: init.manual_entities,
	};
}

/** Sent parameters -> the wizard form they came from (as far as the submit keeps it). */
export function formFromParams({ engine, worldConfig, characterData, manualEntities }) {
	return {
		engine: engine || INITIAL_WIZARD_FORM.engine,
		worldConfig: { ...INITIAL_WIZARD_FORM.worldConfig, ...(worldConfig || {}), lore: worldConfig?.lore || '' },
		characterData: engine === 'd6' && characterData ? d6Character(characterData) : { ...(characterData || {}) },
		manualEntities: { ...(manualEntities || {}) },
	};
}

// The submit sends each D6 skill as its full code (attribute + added dice); the form
// keeps the dice added.
function d6Character(data) {
	if (!Array.isArray(data.skills)) return { ...data };
	const skills = {};
	for (const { attribute, name, dice_value: code } of data.skills) {
		const base = data.attributes?.[attribute];
		const added = parseDice(code) - parseDice(base, Infinity);
		if (name && added > 0) skills[name] = formatDice(added);
	}
	return { ...data, skills };
}
