import asyncio

import pytest

from pendant_server import protocol as P
from pendant_server.backends.mock import MockSTT, MockLLM, MockTTS
from pendant_server.pipeline import Pipeline
from pendant_server.session import Session

pytestmark = pytest.mark.asyncio


class FakeTransport:
    def __init__(self):
        self.texts = []
        self.audio = []

    async def send_text(self, s):
        self.texts.append(P.decode(s))

    async def send_bytes(self, b):
        self.audio.append(b)


def _session(transport, **kw):
    pipe = Pipeline(MockSTT(finalize_s=0.0), MockLLM(ttft_s=0.0, token_s=0.001), MockTTS(first_chunk_s=0.0))
    return Session(pipe, transport.send_text, transport.send_bytes, **kw)


async def _drive_turn(sess, transport, turn, n_frames=20):
    await sess.on_text(P.encode(P.start(turn)))
    for _ in range(n_frames):
        await sess.on_bytes(b"\x00\x00" * (P.FRAME_BYTES // 2))
    await sess.on_text(P.encode(P.end(turn)))


async def _wait_for_done(transport, turn, timeout=5.0):
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        for m in transport.texts:
            if m.get("t") == P.DONE and m.get("turn") == turn:
                return m
        await asyncio.sleep(0.01)
    raise AssertionError(f"turn {turn} never completed; saw {transport.texts}")


async def test_hello_ready_handshake():
    tx = FakeTransport()
    sess = _session(tx)
    await sess.on_text(P.encode(P.hello()))
    assert tx.texts[0]["t"] == P.READY
    assert sess.ready


async def test_ping_pong():
    tx = FakeTransport()
    sess = _session(tx)
    await sess.on_text(P.encode(P.ping(42)))
    assert tx.texts[-1] == {"t": P.PONG, "ts": 42}


async def test_full_turn_emits_done_with_metrics():
    tx = FakeTransport()
    sess = _session(tx)
    await sess.on_text(P.encode(P.hello()))
    await _drive_turn(sess, tx, 1)
    done = await _wait_for_done(tx, 1)
    assert done["metrics"]["ttfa_ms"] is not None
    assert len(tx.audio) > 0
    # A final transcript was reported before audio.
    assert any(m.get("t") == P.FINAL for m in tx.texts)


async def test_barge_in_cancels_previous_turn():
    tx = FakeTransport()
    # Slow the LLM so turn 1 is still mid-flight when turn 2 arrives.
    pipe = Pipeline(MockSTT(finalize_s=0.0), MockLLM(ttft_s=0.0, token_s=0.05), MockTTS(first_chunk_s=0.0))
    sess = Session(pipe, tx.send_text, tx.send_bytes)
    await sess.on_text(P.encode(P.hello()))

    # Start turn 1 and end its uplink, but don't wait for completion.
    await sess.on_text(P.encode(P.start(1)))
    for _ in range(10):
        await sess.on_bytes(b"\x00\x00" * (P.FRAME_BYTES // 2))
    await sess.on_text(P.encode(P.end(1)))
    await asyncio.sleep(0.02)  # let turn 1 begin generating

    # Barge in with turn 2.
    await _drive_turn(sess, tx, 2)
    done2 = await _wait_for_done(tx, 2)
    assert done2["turn"] == 2

    # Turn 1 must NOT have produced a 'done' (it was cancelled).
    done1 = [m for m in tx.texts if m.get("t") == P.DONE and m.get("turn") == 1]
    assert done1 == [], "barge-in should cancel turn 1 before it completes"


async def test_history_accumulates_across_turns():
    tx = FakeTransport()
    sess = _session(tx, history_turns=4)
    await sess.on_text(P.encode(P.hello()))
    await _drive_turn(sess, tx, 1); await _wait_for_done(tx, 1)
    await _drive_turn(sess, tx, 2); await _wait_for_done(tx, 2)
    assert len(sess._history) == 2
