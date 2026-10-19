/**
 * Inject bold markers around known entity names in raw text, so ReactMarkdown's
 * strong override can render them with their tooltip.
 *
 * A name is tagged only as a whole word: no Unicode letter or digit may touch it
 * (\b would treat accented letters as boundaries), so "Vergence" stays plain text
 * inside "convergence" (#142). Text already in bold is left as is.
 */
export function injectEntityMarkers(text, tooltipMap) {
	if (!text || !tooltipMap || Object.keys(tooltipMap).length === 0) return text;

	// Longest first, so "Pater Ondrev" wins over "Pater"
	const names = Object.keys(tooltipMap)
		.map(key => tooltipMap[key].name || key)
		.filter(n => n && n.length >= 3)
		.sort((a, b) => b.length - a.length);

	if (names.length === 0) return text;

	const escaped = names.map(n => n.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
	const regex = new RegExp(
		`(?<![\\p{L}\\p{N}])(?<!\\*\\*)(${escaped.join('|')})(?!\\*\\*)(?![\\p{L}\\p{N}])`,
		'giu',
	);
	return text.replace(regex, match => `**${match}**`);
}
