/**
 * LDVELH - Pending Fate roll (#32) helpers.
 */

/**
 * Messages where the last user message shows `playerMessage`, the action the pending roll
 * belongs to (the backend may answer a new message with the roll already waiting).
 * Same array when there is nothing to change.
 */
export function withPendingPlayerMessage(messages, playerMessage) {
	if (!playerMessage) return messages;
	const index = messages.findLastIndex(m => m.role === 'user');
	if (index === -1 || messages[index].content === playerMessage) return messages;
	const out = [...messages];
	out[index] = { ...messages[index], content: playerMessage };
	return out;
}
