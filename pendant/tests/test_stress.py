"""Stress: many concurrent pendants, sustained turns, and barge-in storms.

These exercise the server the way a fleet of necklaces would: lots of
simultaneous sessions, back-to-back turns, and rapid interruptions. They
assert correctness under load and that the latency budget holds, not just
that nothing crashes.
"""

import asyncio
import contextlib
import statistics

import pytest
import websockets

from pendant_server import protocol as P
from pendant_server.config import Config
from pendant_server.server import PendantServer
from pendant_sim import PendantSim

pytestmark = pytest.mark.asyncio


@contextlib.asynccontextmanager
async def running_server(**overrides):
    cfg = Config(host="127.0.0.1", port=0,
                 mock_stt_finalize_s=0.02, mock_llm_ttft_s=0.03,
                 mock_llm_token_s=0.002, mock_tts_first_s=0.02, **overrides)
    srv = PendantServer(cfg)
    await srv.prewarm()
    async with websockets.serve(srv.handler, cfg.host, 0, max_size=None) as ws_server:
        port = ws_server.sockets[0].getsockname()[1]
        yield f"ws://127.0.0.1:{port}{cfg.path}"


async def test_many_concurrent_pendants():
    N = 25
    async with running_server() as uri:
        async def one():
            sim = PendantSim(uri)
            res = await sim.session(turns=2, speech_ms=300, realtime=False)
            return res

        all_results = await asyncio.gather(*[one() for _ in range(N)])

    flat = [r for batch in all_results for r in batch]
    assert len(flat) == N * 2
    assert all(r.ok for r in flat), "some turns failed under concurrency"
    assert all(r.audio_bytes > 0 for r in flat)

    ttfas = [r.server_metrics["ttfa_ms"] for r in flat]
    p95 = sorted(ttfas)[int(len(ttfas) * 0.95) - 1]
    # Under 25x concurrency, p95 TTFA should still stay well under a second.
    assert p95 < 800, f"p95 TTFA under load regressed: {p95}ms (all={statistics.mean(ttfas):.0f} avg)"


async def test_sustained_back_to_back_turns():
    async with running_server() as uri:
        sim = PendantSim(uri)
        results = await sim.session(turns=30, speech_ms=200, realtime=False)
    assert all(r.ok for r in results)
    assert len(results) == 30


async def test_barge_in_storm_is_stable():
    # Hammer start/cancel without finishing turns; the server must stay alive
    # and still serve a clean final turn afterwards.
    async with running_server() as uri:
        async with websockets.connect(uri, max_size=None) as ws:
            await ws.send(P.encode(P.hello()))
            assert P.decode(await ws.recv())["t"] == P.READY

            for turn in range(1, 40):
                await ws.send(P.encode(P.start(turn)))
                await ws.send(b"\x00\x00" * (P.FRAME_BYTES // 2))
                # Immediately barge-in with the next turn (no 'end').
                await asyncio.sleep(0.001)

            # Now run one clean turn to completion.
            final_turn = 100
            await ws.send(P.encode(P.start(final_turn)))
            for _ in range(8):
                await ws.send(b"\x00\x00" * (P.FRAME_BYTES // 2))
            await ws.send(P.encode(P.end(final_turn)))

            saw_done = False
            for _ in range(500):
                msg = await asyncio.wait_for(ws.recv(), timeout=5)
                if isinstance(msg, (bytes, bytearray)):
                    continue
                obj = P.decode(msg)
                if obj.get("t") == P.DONE and obj.get("turn") == final_turn:
                    saw_done = True
                    break
            assert saw_done, "server failed to serve a clean turn after a barge-in storm"
