/**
 * Incremental Server-Sent Events parser.
 *
 * Network reads are not aligned on SSE events: an event can be split across
 * reads, and one read can carry several events. Text is buffered until a blank
 * line ends the event (#14). Feed it already-decoded text (TextDecoder with
 * { stream: true } keeps multi-byte characters intact across reads).
 */
export function createSSEParser(onEvent) {
	// Pending text kept as parts: joining a long event on every small read is quadratic.
	let parts = [];
	let lastChar = '';
	// A read ending in "\r" may be the first half of "\r\n": hold it back.
	let pendingCR = false;

	function dispatch(block) {
		const dataLines = [];
		for (const rawLine of block.split('\n')) {
			if (!rawLine || rawLine.startsWith(':')) continue; // keepalive / comment
			if (!rawLine.startsWith('data:')) continue;
			const value = rawLine.slice(5);
			dataLines.push(value.startsWith(' ') ? value.slice(1) : value);
		}
		if (dataLines.length === 0) return;
		const payload = dataLines.join('\n');
		try {
			onEvent(JSON.parse(payload));
		} catch (e) {
			console.warn(`[SSE] Dropped event that failed to parse or handle (${payload.length} chars):`, e.message);
		}
	}

	return {
		push(text) {
			let raw = (pendingCR ? '\r' : '') + text;
			pendingCR = raw.endsWith('\r');
			if (pendingCR) raw = raw.slice(0, -1);
			const chunk = raw.replace(/\r\n?/g, '\n');
			if (!chunk) return;
			parts.push(chunk);
			// A blank line can only end here if this read contains a newline.
			const mayEnd = chunk.includes('\n\n') || (lastChar === '\n' && chunk[0] === '\n');
			lastChar = chunk[chunk.length - 1];
			if (!mayEnd) return;
			let buffer = parts.join('');
			let end = buffer.indexOf('\n\n');
			while (end !== -1) {
				dispatch(buffer.slice(0, end));
				buffer = buffer.slice(end + 2);
				end = buffer.indexOf('\n\n');
			}
			parts = buffer ? [buffer] : [];
		},
		/** Dispatch a trailing event that was not followed by a blank line. */
		flush() {
			if (pendingCR) parts.push('\n');
			pendingCR = false;
			const buffer = parts.join('');
			if (buffer.trim()) dispatch(buffer);
			parts = [];
			lastChar = '';
		},
	};
}
