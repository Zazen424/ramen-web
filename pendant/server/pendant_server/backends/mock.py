"""Deterministic mock backends.

These let the entire streaming pipeline -- protocol, overlap, sentence
chunking, barge-in, latency accounting, concurrency -- run and be stress
tested anywhere, with no heavy model dependencies. Simulated compute delays
are configurable so the latency harness measures realistic warm-pipeline
behavior. On the Mac mini these are swapped for the real adapters; the
orchestrator does not change.
"""

from __future__ import annotations

import asyncio
import math
import struct
from typing import AsyncIterator, List, Tuple

from .base import LLMBackend, STTBackend, TTSBackend
from ..protocol import SAMPLE_RATE, FRAME_BYTES


class MockSTT(STTBackend):
    """'Transcribes' by counting received audio.

    Real STT can't read mock PCM, so we derive a deterministic transcript
    from how much audio arrived. Partial transcripts are emitted as frames
    stream in (mirroring streaming-during-speech); the final lands after a
    small simulated finalize delay.
    """

    def __init__(self, finalize_s: float = 0.10, transcript: str = "what's my morning brief") -> None:
        self.finalize_s = finalize_s
        self.transcript = transcript

    async def prewarm(self) -> None:
        await asyncio.sleep(0)

    async def transcribe(self, frames: AsyncIterator[bytes]) -> AsyncIterator[Tuple[str, bool]]:
        words = self.transcript.split()
        n_frames = 0
        emitted = 0
        async for frame in frames:
            n_frames += 1
            # Reveal roughly one word per ~5 frames (~200ms) of audio.
            target = min(len(words), n_frames // 5)
            if target > emitted:
                emitted = target
                yield " ".join(words[:emitted]), False
        await asyncio.sleep(self.finalize_s)
        yield self.transcript, True


class MockLLM(LLMBackend):
    """Streams a canned multi-sentence answer token-by-token.

    The multi-sentence shape is the point: it proves the sentence chunker can
    fire sentence #1 to TTS while later sentences are still being generated.
    """

    def __init__(self, ttft_s: float = 0.12, token_s: float = 0.010) -> None:
        self.ttft_s = ttft_s
        self.token_s = token_s

    async def prewarm(self) -> None:
        await asyncio.sleep(0)

    def _answer(self, prompt: str) -> str:
        p = prompt.lower()
        if "brief" in p or "morning" in p:
            return (
                "Good morning. You have three meetings today, the first at nine. "
                "The weather is clear and mild. "
                "Your top story: the project review moved to Thursday."
            )
        return (
            "Here is what I found. "
            "The answer to your question is yes. "
            "Let me know if you want more detail."
        )

    async def generate(self, prompt: str, history: List[Tuple[str, str]]) -> AsyncIterator[str]:
        await asyncio.sleep(self.ttft_s)
        answer = self._answer(prompt)
        # Emit word-by-word with attached spaces so the chunker sees real
        # token boundaries and punctuation.
        tokens = answer.split(" ")
        for i, tok in enumerate(tokens):
            frag = tok if i == len(tokens) - 1 else tok + " "
            yield frag
            await asyncio.sleep(self.token_s)


class MockTTS(TTSBackend):
    """Synthesizes a sine tone whose duration scales with text length.

    Produces real PCM16 bytes so downlink framing, audio_start/audio_end, and
    playback timing are all exercised end to end.
    """

    def __init__(self, first_chunk_s: float = 0.05, freq: float = 220.0) -> None:
        self.first_chunk_s = first_chunk_s
        self.freq = freq

    async def prewarm(self) -> None:
        await asyncio.sleep(0)

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        # ~60ms of audio per word, floored so even short text makes sound.
        words = max(1, len(text.split()))
        total_samples = max(SAMPLE_RATE // 8, int(SAMPLE_RATE * 0.06 * words))
        samples_per_chunk = FRAME_BYTES // 2  # one protocol frame's worth
        await asyncio.sleep(self.first_chunk_s)
        produced = 0
        phase = 0.0
        step = 2 * math.pi * self.freq / SAMPLE_RATE
        while produced < total_samples:
            n = min(samples_per_chunk, total_samples - produced)
            buf = bytearray()
            for _ in range(n):
                val = int(8000 * math.sin(phase))
                buf += struct.pack("<h", val)
                phase += step
            produced += n
            yield bytes(buf)
            # Real-time pacing keeps the downlink honest without blocking long.
            await asyncio.sleep(n / SAMPLE_RATE * 0.25)
