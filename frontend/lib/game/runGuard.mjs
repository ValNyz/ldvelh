/**
 * Only the latest run may commit: start() voids every run started before and returns
 * whether the new run is still the latest (useTooltips: a poll still awaiting when a
 * refresh starts, or when the game changes, must not commit after it).
 */
export function createRunGuard() {
	let latest = 0;
	return {
		start() {
			latest += 1;
			const run = latest;
			return () => run === latest;
		},
	};
}
