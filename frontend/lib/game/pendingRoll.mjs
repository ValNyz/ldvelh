/**
 * LDVELH - Pending Fate roll (#32) helpers.
 */

/**
 * Messages where the last user message shows `playerMessage`, the action the pending roll
 * belongs to (the backend may answer a new message with the roll already waiting).
 * When that action is already shown just before the optimistic message (modal dismissed,
 * then a new message sent), the optimistic message is dropped instead of duplicating it (#80).
 * Same array when there is nothing to change.
 */
export function withPendingPlayerMessage(messages, playerMessage) {
	if (!playerMessage) return messages;
	const index = messages.findLastIndex(m => m.role === 'user');
	if (index === -1 || messages[index].content === playerMessage) return messages;
	const previous = messages[index - 1];
	if (previous?.role === 'user' && previous.content === playerMessage) {
		return [...messages.slice(0, index), ...messages.slice(index + 1)];
	}
	const out = [...messages];
	out[index] = { ...messages[index], content: playerMessage };
	return out;
}

/** Aspect invocation modal data, from a roll_pending event or a loaded game's pending_roll. */
export function toInvocationData(pending) {
	return {
		rollId: pending.roll_id,
		roll: pending.roll,
		aspects: pending.aspects,
		fatePoints: pending.fate_points,
	};
}

/**
 * Modal data for the roll still pending in a game state (load, rollback), or null: a
 * rollback expires the pending roll, so its modal must not survive it (#80).
 */
export function invocationFromState(state) {
	const pending = state?.pending_roll;
	return pending ? toInvocationData(pending) : null;
}
