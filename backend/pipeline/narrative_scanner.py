"""Incremental extraction of `narrative_text` from a JSON object received in chunks.

Each chunk is scanned once: the position and pending state are kept between feeds,
so the total work is linear in the stream length (#90).
"""

import re

from pipeline.json_escape import decode_json_escape

_MARKER = '"narrative_text":'
_SPECIAL = re.compile(r'[\\"]')


class NarrativeScanner:
    """feed() returns the newly displayable text (stripped like str.strip on the whole).

    An escape cut off at the end of the buffer, and trailing whitespace, are held back
    until more input shows they belong to the text. A stream that ends mid-escape
    therefore never emits the fragment.
    """

    def __init__(self) -> None:
        self._buf = ""
        self._pos = 0           # next unscanned index in _buf
        self._in_string = False
        self._closed = False
        self._started = False   # a non-whitespace character was emitted
        self._pending_ws = ""
        self.scanned = 0        # characters examined, for the linear-work test

    def feed(self, chunk: str) -> str:
        if self._closed:
            return ""
        self._buf += chunk
        if not self._in_string and not self._open_string():
            return ""
        return self._strip_incremental(self._scan_string())

    def _open_string(self) -> bool:
        """Locate the opening quote of the value; only the unscanned tail is searched."""
        if self._pos == 0:
            start = self._buf.find(_MARKER)
            if start == -1:
                return False
            self._pos = start + len(_MARKER)
        quote = self._buf.find('"', self._pos)
        if quote == -1:
            return False
        self._pos = quote + 1
        self._in_string = True
        return True

    def _scan_string(self) -> str:
        buf, i, out = self._buf, self._pos, []
        while i < len(buf):
            m = _SPECIAL.search(buf, i)
            stop = m.start() if m else len(buf)
            out.append(buf[i:stop])
            self.scanned += stop - i
            i = stop
            if m is None:
                break
            if buf[i] == '"':
                self._closed = True
                break
            decoded = decode_json_escape(buf, i)
            if decoded is None:
                break
            text, new_i = decoded
            self.scanned += new_i - i
            out.append(text)
            i = new_i
        self._pos = i
        return "".join(out)

    def _strip_incremental(self, text: str) -> str:
        text = self._pending_ws + text
        if not self._started:
            text = text.lstrip()
            self._started = bool(text)
        shown = text.rstrip()
        self._pending_ws = text[len(shown):]
        if self._closed:
            self._pending_ws = ""
        return shown


def extract_narrative_from_partial(partial_json: str) -> str | None:
    """Narrative text of a complete or partial JSON object, None if there is none yet."""
    scanner = NarrativeScanner()
    return scanner.feed(partial_json) or None
