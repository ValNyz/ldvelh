/**
 * LDVELH - Live /chat turn (#143).
 *
 * Leaving a game cuts nothing: its /chat request keeps running and the server commits the
 * turn. The turn is kept as data (its own messages and status) while it runs, so its
 * events update it whether or not its game is open, and reopening that game shows it again.
 *
 * The message reducers work on any message list: the live turn's own messages and the
 * open game's chat are updated with the same functions.
 */

import { withTurnIds } from './chatHistory.mjs';

export const TURN_STATUS = Object.freeze({
	STREAMING: 'streaming', // waiting for the narration (or receiving it)
	EXTRACTING: 'extracting', // narration shown, the server extracts the state
	SAVING: 'saving', // done: committed, waiting for 'saved'
	ENDED: 'ended', // committed and over
	DROPPED: 'dropped', // nothing to show again: error, roll waiting for an invocation, cancel
});

/** A turn starting in `gameId`; `playerMessage` is the action shown with it (none for protocol tokens). */
export function startLiveTurn(gameId, playerMessage = null) {
	return {
		gameId,
		messages: playerMessage ? [{ role: 'user', content: playerMessage }] : [],
		status: TURN_STATUS.STREAMING,
		roll: null, // roll result received, attached to the answer on its first chunk
	};
}

/** Status after the stream event `type` (unchanged for the events that do not move it). */
export function nextTurnStatus(status, type) {
	switch (type) {
		case 'extracting': return TURN_STATUS.EXTRACTING;
		case 'done': return TURN_STATUS.SAVING;
		case 'saved':
		case 'save_unconfirmed': return TURN_STATUS.ENDED;
		// After done the turn is committed whatever comes next.
		case 'error':
		case 'cancel': return status === TURN_STATUS.SAVING || status === TURN_STATUS.ENDED ? status : TURN_STATUS.DROPPED;
		case 'roll_pending': return TURN_STATUS.DROPPED;
		default: return status;
	}
}

/**
 * Turn flags for the chat of its game, from its status: `loading` (narration not over),
 * `extracting`, `saving` and `sending` (the player cannot send yet).
 */
export function turnActivity(turn) {
	const status = turn?.status;
	const running = status === TURN_STATUS.STREAMING || status === TURN_STATUS.EXTRACTING;
	return {
		loading: running,
		sending: running,
		extracting: status === TURN_STATUS.EXTRACTING,
		saving: running || status === TURN_STATUS.SAVING,
	};
}

/** A narration chunk: appended to the streaming answer, or starts it (with `roll` when given). */
export function withChunk(messages, content, roll = null) {
	const last = messages[messages.length - 1];
	if (last?.role === 'assistant' && last.streaming) {
		return [...messages.slice(0, -1), { ...last, content: last.content + content }];
	}
	return [...messages, { role: 'assistant', content, streaming: true, ...(roll ? { roll } : {}) }];
}

/** The narration is over and the state is being extracted: final text shown. */
export function withExtracting(messages, displayText) {
	const last = messages[messages.length - 1];
	if (last?.role !== 'assistant') return messages;
	return [...messages.slice(0, -1), {
		...last,
		content: displayText || last.content,
		streaming: false,
		extracting: true,
	}];
}

/**
 * The answer is done: final text, turn details and the ids the turn was saved with (#55).
 * When the chat already holds the committed turn (reloaded after the commit, before this
 * event), the live copy at its end is dropped instead of being shown twice.
 */
export function withAnswer(messages, displayText, data) {
	const last = messages[messages.length - 1];
	if (last?.role !== 'assistant') return messages;
	const meta = data?.meta;
	if (meta?.assistant_message_id && messages.some(m => m.id === meta.assistant_message_id)) {
		const before = messages[messages.length - 2];
		const liveUser = before?.role === 'user' && !before.id;
		return messages.slice(0, liveUser ? -2 : -1);
	}
	const game = data?.game_state?.game;
	return withTurnIds([...messages.slice(0, -1), {
		...last,
		content: displayText || last.content,
		streaming: false,
		extracting: false,
		cost: meta?.narration_cost || null,
		cycle: game?.current_cycle || null,
		time: game?.time || null,
		game_date: game?.game_date || null,
		location: game?.current_location || null,
	}], meta);
}

/**
 * A reloaded history with the live turn of its game at the end: nothing when the turn has
 * nothing to show again, or when the history already holds it (committed before the
 * reload). An unsaved action at the end of the history (a pending roll's, #32) that the
 * turn shows too is not repeated.
 */
export function withLiveTurn(history, turn) {
	if (!turn || turn.status === TURN_STATUS.DROPPED || turn.messages.length === 0) return history;
	const answerId = turn.messages.find(m => m.role === 'assistant')?.id;
	if (answerId && history.some(m => m.id === answerId)) return history;
	const [first] = turn.messages;
	const last = history[history.length - 1];
	const sameUnsavedAction = first.role === 'user' && last?.role === 'user' && !last.id && last.content === first.content;
	return [...(sameUnsavedAction ? history.slice(0, -1) : history), ...turn.messages];
}
