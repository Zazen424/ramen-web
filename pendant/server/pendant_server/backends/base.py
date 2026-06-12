"""Backend interfaces: STT, LLM, TTS.

These three abstract bases are the seam that lets the *same* orchestration
run with toy mock models here and resident Whisper/Ollama/Piper on the Mac
mini. Each is an async, streaming-first contract:

    * STT consumes a stream of PCM frames and yields partial transcripts,
      finalizing when the uplink ends (button release == endpoint).
    * LLM consumes the final transcript (+ history) and yields tokens.
    * TTS consumes text (one sentence at a time) and yields PCM audio chunks.

Implementations MUST stay warm: load once, never per-request. ``prewarm`` is
called at server start to pay any one-time cost off the hot path.
"""

from __future__ import annotations

import abc
from typing import AsyncIterator, List, Tuple


class STTBackend(abc.ABC):
    """Streaming speech-to-text."""

    @abc.abstractmethod
    async def prewarm(self) -> None:
        ...

    @abc.abstractmethod
    async def transcribe(self, frames: "AsyncIterator[bytes]") -> "AsyncIterator[Tuple[str, bool]]":
        """Consume PCM16 frames; yield ``(text, is_final)``.

        Partial transcripts (``is_final=False``) may be emitted while audio is
        still arriving. Exactly one final transcript (``is_final=True``) is
        emitted after the frame stream is exhausted.
        """
        raise NotImplementedError
        yield "", False  # pragma: no cover - typing hint for async generator


class LLMBackend(abc.ABC):
    """Streaming token generation."""

    @abc.abstractmethod
    async def prewarm(self) -> None:
        ...

    @abc.abstractmethod
    async def generate(
        self, prompt: str, history: List[Tuple[str, str]]
    ) -> "AsyncIterator[str]":
        """Yield response token/text fragments for ``prompt``.

        ``history`` is a sliding window of prior ``(user, assistant)`` turns
        for short-term memory.
        """
        raise NotImplementedError
        yield ""  # pragma: no cover


class TTSBackend(abc.ABC):
    """Streaming text-to-speech."""

    @abc.abstractmethod
    async def prewarm(self) -> None:
        ...

    @abc.abstractmethod
    async def synthesize(self, text: str) -> "AsyncIterator[bytes]":
        """Yield PCM16 mono @ 16 kHz audio chunks for one sentence of ``text``."""
        raise NotImplementedError
        yield b""  # pragma: no cover
