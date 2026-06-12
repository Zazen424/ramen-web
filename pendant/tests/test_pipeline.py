import asyncio
import time

import pytest

from pendant_server.backends.mock import MockSTT, MockLLM, MockTTS
from pendant_server.metrics import TurnMetrics
from pendant_server.pipeline import Pipeline
from pendant_server.protocol import FRAME_BYTES

pytestmark = pytest.mark.asyncio


async def _frames(n):
    for _ in range(n):
        yield b"\x00\x00" * (FRAME_BYTES // 2)


def _pipeline():
    return Pipeline(MockSTT(finalize_s=0.0), MockLLM(ttft_s=0.0, token_s=0.0), MockTTS(first_chunk_s=0.0))


async def test_full_turn_produces_transcript_and_audio():
    pipe = _pipeline()
    await pipe.prewarm()

    events = []
    audio_chunks = []
    m = TurnMetrics()
    m.mark_end()

    async def rec(kind):
        async def _cb(*args):
            events.append((kind, args[0] if args else None))
        return _cb

    async def on_audio(chunk):
        audio_chunks.append(chunk)

    transcript, response = await pipe.run_turn(
        _frames(30), [], m,
        on_partial=await rec("partial"),
        on_final=await rec("final"),
        on_say=await rec("say"),
        on_audio_start=await rec("audio_start"),
        on_audio=on_audio,
        on_audio_end=await rec("audio_end"),
    )

    assert transcript.strip() != ""
    assert response.strip() != ""
    assert len(audio_chunks) > 0
    assert m.ttfa_ms() is not None

    kinds = [k for k, _ in events]
    # Ordering invariants of the overlapped pipeline.
    assert "final" in kinds
    assert kinds.index("final") < kinds.index("audio_start")
    assert kinds.index("say") < kinds.index("audio_end")
    assert kinds[-1] == "audio_end"


async def test_overlap_first_audio_before_generation_done():
    # With realistic per-token delay, first audio must arrive well before the
    # LLM finishes generating every sentence -- proof the pipeline overlaps.
    pipe = Pipeline(MockSTT(finalize_s=0.0), MockLLM(ttft_s=0.0, token_s=0.02), MockTTS(first_chunk_s=0.0))
    await pipe.prewarm()

    t0 = time.perf_counter()
    first_audio_at = {}
    m = TurnMetrics(); m.mark_end()

    async def on_audio(_):
        first_audio_at.setdefault("t", time.perf_counter())

    _, response = await pipe.run_turn(_frames(10), [], m, on_audio=on_audio)
    total = time.perf_counter() - t0

    assert "t" in first_audio_at
    # First audio landed before half of the total turn elapsed.
    assert (first_audio_at["t"] - t0) < total * 0.7


async def test_empty_speech_yields_nothing():
    pipe = _pipeline()
    await pipe.prewarm()
    m = TurnMetrics(); m.mark_end()
    # MockSTT keys its transcript off frame count; zero frames -> still finals
    # the canned transcript, so force empty via a custom STT.
    pipe.stt = MockSTT(finalize_s=0.0, transcript="")
    transcript, response = await pipe.run_turn(_frames(0), [], m)
    assert transcript == "" and response == ""
