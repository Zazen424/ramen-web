"""faster-whisper STT adapter (resident, Metal/CT2).

Used on the Mac mini. Push-to-talk gives us a deterministic endpoint, so we
buffer the streamed frames and transcribe the (short) utterance on finalize;
because most of the audio arrived during speech, the finalize tail is small.
Partial transcripts are emitted on a coarse interval to keep the UI alive.

faster-whisper is imported lazily so this module never blocks the mock path.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, Tuple

import numpy as np

from .base import STTBackend
from ..protocol import SAMPLE_RATE


class WhisperSTT(STTBackend):
    def __init__(self, model: str = "distil-small.en", compute_type: str = "int8") -> None:
        self._model_name = model
        self._compute_type = compute_type
        self._model = None  # set in prewarm

    async def prewarm(self) -> None:
        def _load():
            from faster_whisper import WhisperModel
            m = WhisperModel(self._model_name, device="auto", compute_type=self._compute_type)
            # Dummy inference to pay graph/JIT cost off the hot path.
            list(m.transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32))[0])
            return m

        self._model = await asyncio.to_thread(_load)

    async def transcribe(self, frames: AsyncIterator[bytes]) -> AsyncIterator[Tuple[str, bool]]:
        assert self._model is not None, "call prewarm() first"
        pcm = bytearray()
        last_partial_at = 0
        async for frame in frames:
            pcm += frame
            # Emit a partial roughly every ~0.5s of audio.
            if len(pcm) - last_partial_at >= SAMPLE_RATE * 2:  # 0.5s * 2 bytes/sample * ...
                last_partial_at = len(pcm)
                text = await self._run(bytes(pcm))
                if text:
                    yield text, False
        final_text = await self._run(bytes(pcm))
        yield final_text, True

    async def _run(self, pcm: bytes) -> str:
        if not pcm:
            return ""
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0

        def _infer() -> str:
            segments, _ = self._model.transcribe(audio, language="en", beam_size=1)
            return " ".join(s.text.strip() for s in segments).strip()

        return await asyncio.to_thread(_infer)
