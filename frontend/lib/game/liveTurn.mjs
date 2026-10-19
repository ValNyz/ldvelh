/**
 * LDVELH - Live /chat turn (#143).
 *
 * Leaving a game cuts nothing: its /chat request keeps running and the server commits the
 * turn. The turn is kept as data (its messages, status and the results its events carried)
 * while it runs, so its events update it whether or not its game is open, and reopening
 * that game shows it again (`reopenTurn`).
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
	DROPPED: 'dropped', // not committed: error, roll waiting for an invocation, cancel
});

/** What the turn plays: a world generation (__INIT__), the arrival scene, or a player action. */
export const TURN_KIND = Object.freeze({ INIT: 'init', ARRIVAL: 'arrival', ACTION: 'action' });

/**
 * A turn starting in `gameId`; `playerMessage` is the action shown with it (none for the
 * protocol turns).
 */
export function startLiveTurn(gameId, { kind = TURN_KIND.ACTION, playerMessage = null } = {}) {
	return {
		gameId,
		kind,
		messages: playerMessage ? [{ role: 'user', content: playerMessage }] : [],
		status: TURN_STATUS.STREAMING,
		roll: null, // roll result received, attached to the answer on its first chunk
		progress: '', // world generation JSON so far (init)
		director: null, // { status, label } of the scenario step (init)
		gameState: null, // game state of the done event
		world: null, // world info of the done event (init)
		warning: null, // last notice for the turn
		error: null, // { message, details, recoverable, code } of the error event
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
 * The turn after the stream event `type` (or 'cancel'): its status moves, `edit` updates
 * its messages, and `fields` stores what the event carried. The only place a turn changes.
 */
export function withTurnEvent(turn, type, { edit = null, ...fields } = {}) {
	return {
		...turn,
		...fields,
		status: nextTurnStatus(turn.status, type),
		messages: edit ? edit(turn.messages) : turn.messages,
	};
}

const isRunning = (turn) => turn?.status === TURN_STATUS.STREAMING || turn?.status === TURN_STATUS.EXTRACTING;

/**
 * Turn flags for its game, from its status: `loading` (not over), `extracting`, `saving`
 * and `sending` (the player cannot send yet). As when the turn started: an action sets them
 * all, a protocol turn only `loading` (and `saving` once done).
 */
export function turnActivity(turn) {
	const running = isRunning(turn);
	const saving = turn?.status === TURN_STATUS.SAVING;
	if (turn && turn.kind !== TURN_KIND.ACTION) {
		return { loading: running, sending: false, extracting: false, saving };
	}
	return {
		loading: running,
		sending: running,
		extracting: turn?.status === TURN_STATUS.EXTRACTING,
		saving: running || saving,
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
		if (last.id) return messages; // only the committed turn is shown
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
 * A reloaded history with the live turn of its game at the end, when the history does not
 * hold it yet:
 * - nothing for a dropped turn, except its action when it failed with an error (shown with
 *   the error, to retry it);
 * - nothing when the history holds the committed turn: by its answer's id, or, before its
 *   ids are known (extracting: committed or about to be), by the same action and answer at
 *   the end of the history.
 * An unsaved action at the end of the history (a pending roll's, #32) that the turn shows
 * too is not repeated.
 */
export function withLiveTurn(history, turn) {
	if (!turn || turn.messages.length === 0) return history;
	let shown = turn.messages;
	if (turn.status === TURN_STATUS.DROPPED) {
		if (!turn.error || turn.messages[0].role !== 'user') return history;
		shown = turn.messages.slice(0, 1);
	} else if (holdsTurn(history, turn)) {
		return history;
	}
	const [first] = shown;
	const last = history[history.length - 1];
	const sameUnsavedAction = first.role === 'user' && last?.role === 'user' && !last.id && last.content === first.content;
	return [...(sameUnsavedAction ? history.slice(0, -1) : history), ...shown];
}

function holdsTurn(history, turn) {
	const answer = turn.messages.find(m => m.role === 'assistant');
	if (answer?.id) return history.some(m => m.id === answer.id);
	if (turn.status !== TURN_STATUS.EXTRACTING || !answer) return false;
	const action = turn.messages.find(m => m.role === 'user');
	const [before, last] = history.slice(-2);
	return last?.role === 'assistant' && last.content === answer.content
		&& (!action || (before?.role === 'user' && before.content === action.content));
}

/**
 * How the game `history` was loaded for shows its live `turn` again (none: null turn).
 * `worldCreated`: the loaded state says the world exists. Returns:
 * - messages: the chat to show (`withLiveTurn`);
 * - attached: the turn's events drive this game from now on (running, or newer than the load);
 * - activity: the turn flags to restore (`turnActivity`), idle when not attached;
 * - action: the player's action of the turn shown again (to retry it), or null;
 * - generating: { progress, director } of a world generation still running, or null;
 * - starting: an arrival scene still running;
 * - world: { info, gameState } of a world generation done after the load was read, or null;
 * - gameState: the state of a turn done after the load was read (newer: applied over it), or null;
 * - error, warning: what the turn's events reported while the game was closed;
 * - refresh: the turn was saved after the load was read (refresh what depends on it).
 */
export function reopenTurn(history, turn, { worldCreated = false } = {}) {
	const messages = withLiveTurn(history, turn);
	const merged = messages !== history;
	const running = isRunning(turn);
	const kind = turn?.kind;
	const committed = turn?.status === TURN_STATUS.SAVING || turn?.status === TURN_STATUS.ENDED;
	// The load was read before the commit: the turn's results are newer than it.
	const newer = committed && (kind === TURN_KIND.INIT ? !worldCreated : merged);
	const attached = Boolean(turn) && (running ? (kind !== TURN_KIND.ACTION || merged) : newer);
	const action = merged ? turn.messages.find(m => m.role === 'user')?.content ?? null : null;
	return {
		messages,
		attached,
		activity: turnActivity(attached ? turn : null),
		action,
		generating: running && kind === TURN_KIND.INIT ? { progress: turn.progress, director: turn.director } : null,
		starting: running && kind === TURN_KIND.ARRIVAL,
		world: newer && kind === TURN_KIND.INIT && turn.world ? { info: turn.world, gameState: turn.gameState } : null,
		gameState: newer && kind !== TURN_KIND.INIT ? turn.gameState : null,
		error: turn?.error ?? null,
		warning: attached || merged ? turn.warning : null,
		refresh: newer && turn.status === TURN_STATUS.ENDED,
	};
}
