"""Piper TTS adapter (resident, ONNX/NEON, streaming-ish).

Piper synthesizes a sentence to PCM very fast (sub-50ms first audio on Apple
silicon). We resample/emit 16 kHz mono PCM16 frames so the pendant can play
them straight through its I2S amp. Imported lazily.
"""

from __future__ import annotations

import asyncio
import wave
import io
from typing import AsyncIterator

import numpy as np

from .base import TTSBackend
from ..protocol import SAMPLE_RATE, FRAME_BYTES


class PiperTTS(TTSBackend):
    def __init__(self, voice: str = "en_US-amy-medium") -> None:
        self._voice_name = voice
        self._voice = None  # set in prewarm

    async def prewarm(self) -> None:
        def _load():
            from piper.voice import PiperVoice  # type: ignore
            v = PiperVoice.load(self._voice_name)
            return v

        self._voice = await asyncio.to_thread(_load)
        # Warm the graph with a throwaway synth.
        async for _ in self.synthesize("ready"):
            break

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        assert self._voice is not None, "call prewarm() first"

        def _synth() -> bytes:
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                self._voice.synthesize(text, wf)
            return buf.getvalue()

        wav_bytes = await asyncio.to_thread(_synth)
        pcm = _wav_to_pcm16_16k(wav_bytes)
        # Re-frame into protocol-sized chunks and stream them.
        for i in range(0, len(pcm), FRAME_BYTES):
            yield pcm[i : i + FRAME_BYTES]


def _wav_to_pcm16_16k(wav_bytes: bytes) -> bytes:
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        sr = wf.getframerate()
        n = wf.getnframes()
        raw = wf.readframes(n)
        ch = wf.getnchannels()
    audio = np.frombuffer(raw, dtype=np.int16)
    if ch > 1:
        audio = audio.reshape(-1, ch).mean(axis=1).astype(np.int16)
    if sr != SAMPLE_RATE:
        # Linear resample to 16 kHz (good enough for speech playback).
        idx = np.linspace(0, len(audio) - 1, int(len(audio) * SAMPLE_RATE / sr))
        audio = np.interp(idx, np.arange(len(audio)), audio).astype(np.int16)
    return audio.tobytes()
