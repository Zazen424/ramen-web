"""Incremental sentence chunker.

Feeds the LLM's token stream in and flushes a complete sentence the instant a
clause boundary appears, so TTS can start on sentence #1 before the full
answer exists. This is the heart of the LLM->TTS overlap that makes first
audio leave early.
"""

from __future__ import annotations

from typing import Iterator, List

# Sentence-final punctuation. We flush on these when followed by whitespace or
# end-of-buffer, which avoids splitting on "9 a.m." style mid-sentence dots in
# the common case (a trailing dot with no following space is held).
_TERMINATORS = ".!?"


class SentenceChunker:
    """Accumulates token fragments; emits whole sentences as they complete."""

    def __init__(self, min_chars: int = 2) -> None:
        self._buf = ""
        self._min_chars = min_chars

    def push(self, fragment: str) -> List[str]:
        """Add a token fragment; return any sentences now complete."""
        self._buf += fragment
        out: List[str] = []
        while True:
            idx = self._next_boundary(self._buf)
            if idx is None:
                break
            sentence = self._buf[: idx + 1].strip()
            self._buf = self._buf[idx + 1 :].lstrip()
            if len(sentence) >= self._min_chars:
                out.append(sentence)
        return out

    def flush(self) -> List[str]:
        """Emit whatever remains (the final, possibly unterminated, sentence)."""
        tail = self._buf.strip()
        self._buf = ""
        return [tail] if len(tail) >= self._min_chars else []

    @staticmethod
    def _next_boundary(buf: str) -> "int | None":
        for i, ch in enumerate(buf):
            if ch not in _TERMINATORS:
                continue
            nxt = buf[i + 1] if i + 1 < len(buf) else ""
            # Boundary requires the terminator to be followed by whitespace or
            # end-of-buffer (a word boundary).
            if nxt != "" and not nxt.isspace():
                continue
            # Suppress dotted abbreviations like "a.m.", "e.g.", "U.S." -- a
            # period two chars after another period is almost always an
            # abbreviation, not a sentence end. (Costs us nothing on real
            # sentence ends, which don't have an internal dot.)
            if ch == "." and i >= 2 and buf[i - 2] == ".":
                continue
            return i
        return None


def split_sentences(text: str) -> Iterator[str]:
    """Convenience: chunk a complete string into sentences."""
    c = SentenceChunker()
    for s in c.push(text):
        yield s
    for s in c.flush():
        yield s
