/**
 * LDVELH - Chat history helpers: the action to regenerate, the ids of a live turn (#55).
 */

/** The last message the player wrote (scanning backwards), or null. */
export function findLastUserMessage(messages) {
	return messages.findLast(m => m.role === 'user') ?? null;
}

/**
 * Messages where the turn just answered carries the ids the server saved it with (done
 * event meta): the last assistant message, and the action just before it when there is one
 * (the arrival's protocol token is not shown). Same array when there is nothing to set.
 */
export function withTurnIds(messages, meta) {
	const { user_message_id: userId, assistant_message_id: assistantId } = meta || {};
	const index = messages.findLastIndex(m => m.role === 'assistant');
	if (!assistantId || index === -1) return messages;
	const out = [...messages];
	out[index] = { ...messages[index], id: assistantId };
	if (userId && messages[index - 1]?.role === 'user') {
		out[index - 1] = { ...messages[index - 1], id: userId };
	}
	return out;
}
