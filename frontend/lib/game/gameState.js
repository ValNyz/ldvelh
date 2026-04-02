/**
 * LDVELH - Game State Utilities (Frontend)
 *
 * Simplified: the Python server handles normalization.
 * This file only does local merge for SSE updates.
 */

// ============================================================================
// CONSTANTS (copy of Python values for fallback)
// ============================================================================

export const DEFAULT_STATS = {
	energy: 3.0,
	morale: 3.0,
	health: 4.0,
	credits: 1400
};

// ============================================================================
// VALIDATION
// ============================================================================

/**
 * Check if a state is valid (comes from normalized Python server)
 */
export function isValidGameState(state) {
	if (!state) return false;
	return state.game !== undefined || state.player !== undefined;
}

/**
 * Normalize a state (no-op if already normalized by server)
 */
export function normalizeGameState(state) {
	if (!state) return null;

	return {
		game: state.game || null,
		player: state.player || { ...DEFAULT_STATS, inventory: [] },
		ai: state.ai || null,
		world_created: state.world_created || false
	};
}

// ============================================================================
// MERGE HELPERS (for partial SSE updates)
// ============================================================================

/**
 * Merge two game states
 */
export function mergeGameStates(prev, next) {
	if (!prev) return next;
	if (!next) return prev;

	return {
		game: mergeObjects(prev.game, next.game),
		player: mergePlayer(prev.player, next.player),
		ai: mergeObjects(prev.ai, next.ai),
		world_created: next.world_created ?? prev.world_created ?? false
	};
}

/**
 * Special merge for player (inventory is always replaced)
 */
function mergePlayer(prev, next) {
	if (!prev) return next;
	if (!next) return prev;

	return {
		energy: next.energy ?? prev.energy,
		morale: next.morale ?? prev.morale,
		health: next.health ?? prev.health,
		credits: next.credits ?? prev.credits,
		inventory: next.inventory !== undefined ? next.inventory : prev.inventory
	};
}

/**
 * Generic object merge (ignores null/undefined)
 */
function mergeObjects(prev, next) {
	if (!prev) return next;
	if (!next) return prev;

	const result = { ...prev };
	for (const [key, value] of Object.entries(next)) {
		if (value !== null && value !== undefined) {
			result[key] = value;
		}
	}
	return result;
}

