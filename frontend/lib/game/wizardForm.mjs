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

export const PROTAGONIST_REF = 'PROTAGONIST';
export const INVALID_PC_NAME =
	`Nom du protagoniste invalide : les caractères < et > et le nom « ${PROTAGONIST_REF} » sont réservés.`;

/**
 * Same rule as the API (schema.core.is_usable_protagonist_name, #28; shared cases in
 * tests/fixtures/protagonist-names.json): a typed name must not contain '<' or '>' nor be the
 * reserved reference (trimmed, lower-cased, as the backend compares it). Blank is fine, the world
 * builder invents one.
 * @returns {string|null} the French message to show, or null when the name is acceptable
 */
export function protagonistNameError(name) {
	const typed = (name || '').trim();
	if (!typed) return null;
	const reserved = typed.includes('<') || typed.includes('>') || typed.toLowerCase() === PROTAGONIST_REF.toLowerCase();
	return reserved ? INVALID_PC_NAME : null;
}
