/**
 * LDVELH - Creation wizard form model
 * Steps and the empty form, shared by the wizard and its draft.
 */

export const WIZARD_STEPS = ['engine', 'world', 'character'];
export const WIZARD_STEP_LABELS = ['Moteur', 'Monde', 'Personnage'];

export const INITIAL_WIZARD_FORM = Object.freeze({
	engine: 'none',
	worldConfig: Object.freeze({
		genre: 'sci_fi',
		difficulty: 'moderate',
		duration: 'medium',
		hardcore: false,
		lore: '',
	}),
	characterData: Object.freeze({}),
	manualEntities: Object.freeze({}),
});
