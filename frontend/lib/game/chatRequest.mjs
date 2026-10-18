/**
 * LDVELH - The /chat request body, built in this one place (#55).
 */

/**
 * Body of a /chat call for `gameId`, with the player's provider and model; `extra` carries
 * the call's own fields (message, roll resume, wizard parameters). The client game state
 * is never sent: the server reloads it from the database.
 */
export function buildChatPayload({ gameId, preferences }, extra = {}) {
	return {
		gameId,
		provider: preferences?.activeProvider || 'anthropic',
		model: preferences?.activeModel || null,
		...extra,
	};
}
