"""Per-connection session: turn lifecycle, barge-in, history, transport glue.

Owns one pendant WebSocket. Routes inbound control/audio to the active turn,
wires pipeline callbacks back to outbound WebSocket sends, keeps a sliding
window of conversation history, and implements barge-in as task cancellation.

This is the only layer that touches the socket; ``Pipeline`` stays transport
free.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable, List, Optional, Tuple

from . import protocol as P
from .metrics import TurnMetrics
from .pipeline import Pipeline

log = logging.getLogger("pendant.session")

# Minimal transport surface so tests can drive a session without real sockets.
SendText = Callable[[str], Awaitable[None]]


@dataclass
class _Turn:
    turn_id: int
    frame_q: "asyncio.Queue[Optional[bytes]]" = field(default_factory=asyncio.Queue)
    metrics: TurnMetrics = field(default_factory=TurnMetrics)
    task: "Optional[asyncio.Task[Any]]" = None


async def _frame_iter(q: "asyncio.Queue[Optional[bytes]]") -> AsyncIterator[bytes]:
    while True:
        item = await q.get()
        if item is None:
            return
        yield item


class Session:
    def __init__(
        self,
        pipeline: Pipeline,
        send_text: SendText,
        send_bytes: Callable[[bytes], Awaitable[None]],
        *,
        history_turns: int = 6,
        turn_timeout_s: float = 20.0,
    ) -> None:
        self._pipeline = pipeline
        self._raw_send_text = send_text
        self._raw_send_bytes = send_bytes
        self._history_turns = history_turns
        self._turn_timeout_s = turn_timeout_s

        self._history: List[Tuple[str, str]] = []
        self._active: Optional[_Turn] = None
        self._send_lock = asyncio.Lock()  # serialize writes (turn task vs recv loop)
        self.ready = False

    # ---- outbound (lock-guarded) --------------------------------------------

    async def _send(self, msg: dict) -> None:
        async with self._send_lock:
            await self._raw_send_text(P.encode(msg))

    async def _send_audio(self, chunk: bytes) -> None:
        async with self._send_lock:
            await self._raw_send_bytes(chunk)

    # ---- inbound dispatch ----------------------------------------------------

    async def on_text(self, text: str) -> None:
        try:
            msg = P.decode(text)
        except ValueError as exc:
            await self._send(P.error(str(exc)))
            return
        t = msg.get("t")
        if t == P.HELLO:
            self.ready = True
            await self._send(P.ready())
        elif t == P.PING:
            await self._send(P.pong(int(msg.get("ts", 0))))
        elif t == P.START:
            await self._start_turn(int(msg.get("turn", 0)))
        elif t == P.END:
            self._end_uplink(int(msg.get("turn", 0)))
        elif t == P.CANCEL:
            await self._cancel_active(int(msg.get("turn", 0)))
        else:
            await self._send(P.error(f"unknown type: {t}"))

    async def on_bytes(self, data: bytes) -> None:
        """Route a mic audio frame to the active turn (ignored if none)."""
        turn = self._active
        if turn is not None:
            turn.metrics  # noqa: B018 - touch to keep attr (no-op)
            turn.frame_q.put_nowait(data)

    # ---- turn control --------------------------------------------------------

    async def _start_turn(self, turn_id: int) -> None:
        # Barge-in: a new turn supersedes any in-flight one.
        if self._active is not None:
            await self._cancel_active(self._active.turn_id, notify=False)
        turn = _Turn(turn_id=turn_id)
        turn.task = asyncio.create_task(self._run_turn(turn))
        self._active = turn

    def _end_uplink(self, turn_id: int) -> None:
        turn = self._active
        if turn is None or turn.turn_id != turn_id:
            return
        # Endpoint timestamp: this is where TTFA starts counting.
        turn.metrics.mark_end()
        turn.frame_q.put_nowait(None)  # close the frame stream

    async def _cancel_active(self, turn_id: int, notify: bool = True) -> None:
        turn = self._active
        if turn is None or turn.turn_id != turn_id:
            return
        turn.metrics.cancelled = True
        if turn.task is not None and not turn.task.done():
            turn.task.cancel()
            try:
                await turn.task
            except asyncio.CancelledError:
                pass
        if self._active is turn:
            self._active = None

    async def _run_turn(self, turn: _Turn) -> None:
        tid = turn.turn_id

        async def on_partial(text: str) -> None:
            await self._send(P.partial(tid, text))

        async def on_final(text: str) -> None:
            await self._send(P.final(tid, text))

        async def on_say(text: str) -> None:
            await self._send(P.say(tid, text))

        async def on_audio_start() -> None:
            await self._send(P.audio_start(tid))

        async def on_audio(chunk: bytes) -> None:
            await self._send_audio(chunk)

        async def on_audio_end() -> None:
            await self._send(P.audio_end(tid))

        try:
            transcript, response = await asyncio.wait_for(
                self._pipeline.run_turn(
                    _frame_iter(turn.frame_q),
                    list(self._history),
                    turn.metrics,
                    on_partial=on_partial,
                    on_final=on_final,
                    on_say=on_say,
                    on_audio_start=on_audio_start,
                    on_audio=on_audio,
                    on_audio_end=on_audio_end,
                ),
                timeout=self._turn_timeout_s,
            )
            turn.metrics.mark_done()
            await self._send(P.done(tid, turn.metrics.as_dict()))
            if transcript and response:
                self._history.append((transcript, response))
                if len(self._history) > self._history_turns:
                    self._history = self._history[-self._history_turns :]
        except asyncio.CancelledError:
            log.debug("turn %s cancelled (barge-in)", tid)
            raise
        except asyncio.TimeoutError:
            log.warning("turn %s timed out", tid)
            await self._send(P.error(f"turn {tid} timed out"))
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("turn %s failed", tid)
            await self._send(P.error(f"turn {tid} failed: {exc}"))
        finally:
            if self._active is turn:
                self._active = None
