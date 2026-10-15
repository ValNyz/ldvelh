/**
 * LDVELH - D6 dice codes for character creation.
 * 1D = 3 pips; "3D+1" = 10 pips.
 */

/** "3D+1" -> 10 pips; empty or unreadable -> fallback. */
export function parseDice(code, fallback = 0) {
	if (!code) return fallback;
	const m = String(code).match(/(\d+)\s*D(?:\s*\+\s*(\d+))?/i);
	if (!m) return fallback;
	return parseInt(m[1], 10) * 3 + parseInt(m[2] || '0', 10);
}

/** 10 pips -> "3D+1". */
export function formatDice(pips) {
	const dice = Math.floor(pips / 3);
	const rem = pips % 3;
	return rem > 0 ? `${dice}D+${rem}` : `${dice}D`;
}

/**
 * Wizard skills {name: dice added} -> the list the backend stores
 * [{attribute, name, dice_value}], where dice_value is the full code
 * (attribute + added dice) used for rolls. Skills not in the genre's list are dropped.
 * @param {Object} skills - {"Esquive": "1D+1"}
 * @param {Object} attributes - {"Dextérité": "3D"} (missing attributes count as 2D)
 * @param {Object} skillsByAttribute - {"Dextérité": ["Esquive", ...]}
 */
export function d6SkillsForSubmit(skills, attributes, skillsByAttribute) {
	const out = [];
	for (const [attribute, names] of Object.entries(skillsByAttribute)) {
		for (const name of names) {
			const added = parseDice(skills?.[name]);
			if (added <= 0) continue;
			const base = parseDice(attributes?.[attribute], 6);
			out.push({ attribute, name, dice_value: formatDice(base + added) });
		}
	}
	return out;
}
