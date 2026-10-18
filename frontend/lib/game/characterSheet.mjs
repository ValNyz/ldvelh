/**
 * Character sheet display helpers (pure): Fate skill pyramid, D6 skills under their attribute.
 * Input is `player.sheet` from the backend (engine.get_sheet_display, #93).
 */

export const ASPECT_TYPE_LABELS = { high_concept: 'Concept', trouble: 'Problème', other: 'Aspect' };

/** Case- and accent-insensitive key ("Dexterite" == "Dextérité"). */
const fold = (name) => String(name ?? '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').trim().toLowerCase();

/** Fate level as "+2" / "0" / "-1". */
export function formatFateLevel(level) {
	const n = Number(level) || 0;
	return n > 0 ? `+${n}` : String(n);
}

/** Skills grouped by level, highest first: [{ level, label, skills: [name] }]. */
export function fateSkillPyramid(skills = []) {
	const byLevel = new Map();
	for (const s of skills) {
		const level = Number(s.level) || 0;
		if (!byLevel.has(level)) byLevel.set(level, { level, label: s.label || '', skills: [] });
		byLevel.get(level).skills.push(s.name);
	}
	return [...byLevel.values()].sort((a, b) => b.level - a.level);
}

/**
 * Attributes in sheet order, each with its skills: { rows: [{ name, dice, skills }], others }.
 * Skills whose attribute is not on the sheet go to `others`.
 */
export function d6SkillsByAttribute(attributes = {}, skills = []) {
	const rows = Object.entries(attributes).map(([name, dice]) => ({ name, dice, skills: [] }));
	const byKey = new Map(rows.map(r => [fold(r.name), r]));
	const others = [];
	for (const s of skills) (byKey.get(fold(s.attribute))?.skills ?? others).push(s);
	return { rows, others };
}

/**
 * Stunt as { name, description }, or null when it has no text. Stunts are plain strings
 * or {name, description} dicts; progression may store an empty name.
 */
export function stuntText(stunt) {
	if (typeof stunt === 'string') return stunt.trim() ? { name: stunt.trim(), description: '' } : null;
	const name = String(stunt?.name ?? '').trim();
	const description = String(stunt?.description ?? '').trim();
	if (!name && !description) return null;
	return name ? { name, description } : { name: description, description: '' };
}
