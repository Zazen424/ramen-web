"""The streaming response pipeline: STT -> LLM -> TTS, overlapped.

One ``run_turn`` call drives a single turn. The stages are joined by
``asyncio`` queues so they run concurrently:

    mic frames --> [STT] --final text--> [LLM] --tokens--> [chunker]
                                                              |
                                                         sentences
                                                              v
                                                   [TTS] --PCM chunks--> sink

Callbacks (``on_*``) decouple the pipeline from the transport: the session
layer wires them to WebSocket sends. The pipeline never touches a socket, so
it is unit-testable in isolation.

Barge-in is cooperative cancellation: cancel the asyncio task running the
turn; the ``finally`` blocks below stop the stages cleanly.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, Awaitable, Callable, List, Optional, Tuple

from .backends.base import LLMBackend, STTBackend, TTSBackend
from .metrics import TurnMetrics
from .sentence_chunker import SentenceChunker


# Callback signatures (all async). Any may be None.
PartialCb = Callable[[str], Awaitable[None]]
FinalCb = Callable[[str], Awaitable[None]]
SayCb = Callable[[str], Awaitable[None]]
AudioStartCb = Callable[[], Awaitable[None]]
AudioCb = Callable[[bytes], Awaitable[None]]
AudioEndCb = Callable[[], Awaitable[None]]


class Pipeline:
    def __init__(self, stt: STTBackend, llm: LLMBackend, tts: TTSBackend) -> None:
        self.stt = stt
        self.llm = llm
        self.tts = tts

    async def prewarm(self) -> None:
        """Pay one-time model costs off the hot path."""
        await asyncio.gather(self.stt.prewarm(), self.llm.prewarm(), self.tts.prewarm())

    async def run_turn(
        self,
        frames: "AsyncIterator[bytes]",
        history: List[Tuple[str, str]],
        metrics: TurnMetrics,
        *,
        on_partial: Optional[PartialCb] = None,
        on_final: Optional[FinalCb] = None,
        on_say: Optional[SayCb] = None,
        on_audio_start: Optional[AudioStartCb] = None,
        on_audio: Optional[AudioCb] = None,
        on_audio_end: Optional[AudioEndCb] = None,
    ) -> Tuple[str, str]:
        """Run one full turn. Returns ``(transcript, response_text)``.

        ``frames`` must be an async iterator of PCM16 frames that ends when the
        uplink ends (the session closes it on ``end``).
        """

        # ---- Stage 1: STT (streams partials, produces one final) -------------
        final_text = ""
        async for text, is_final in self.stt.transcribe(frames):
            if is_final:
                final_text = text
                metrics.mark_asr_final()
                if on_final:
                    await on_final(text)
            else:
                if on_partial:
                    await on_partial(text)

        if not final_text.strip():
            # Nothing intelligible -- nothing to say.
            return "", ""

        # ---- Stages 2+3: LLM tokens -> sentence chunker -> TTS ---------------
        # A bounded queue of sentences decouples generation speed from synth
        # speed and applies natural backpressure.
        sentence_q: "asyncio.Queue[Optional[str]]" = asyncio.Queue(maxsize=8)
        response_parts: List[str] = []
        audio_started = False

        async def produce_sentences() -> None:
            chunker = SentenceChunker()
            first = True
            async for frag in self.llm.generate(final_text, history):
                if first:
                    metrics.mark_llm_first()
                    first = False
                for sentence in chunker.push(frag):
                    await sentence_q.put(sentence)
            for sentence in chunker.flush():
                await sentence_q.put(sentence)
            await sentence_q.put(None)  # sentinel: no more sentences

        async def consume_sentences() -> None:
            nonlocal audio_started
            while True:
                sentence = await sentence_q.get()
                if sentence is None:
                    break
                response_parts.append(sentence)
                if on_say:
                    await on_say(sentence)
                # Synthesize this sentence and stream its audio immediately.
                async for chunk in self.tts.synthesize(sentence):
                    if not audio_started:
                        audio_started = True
                        if on_audio_start:
                            await on_audio_start()
                    metrics.mark_first_audio()
                    metrics.audio_bytes += len(chunk)
                    if on_audio:
                        await on_audio(chunk)

        producer = asyncio.create_task(produce_sentences())
        consumer = asyncio.create_task(consume_sentences())
        try:
            await asyncio.gather(producer, consumer)
        finally:
            # On cancellation/error, make sure neither task is left dangling.
            for task in (producer, consumer):
                if not task.done():
                    task.cancel()
            if audio_started and on_audio_end:
                await on_audio_end()

        return final_text, " ".join(response_parts)
