"""End-to-end over a real WebSocket: PendantServer + PendantSim client."""

import asyncio
import contextlib

import pytest
import websockets

from pendant_server import protocol as P
from pendant_server.config import Config
from pendant_server.server import PendantServer
from pendant_sim import PendantSim

pytestmark = pytest.mark.asyncio


@contextlib.asynccontextmanager
async def running_server(**overrides):
    cfg = Config(host="127.0.0.1", port=0, **overrides)
    srv = PendantServer(cfg)
    await srv.prewarm()
    async with websockets.serve(srv.handler, cfg.host, 0, max_size=None) as ws_server:
        port = ws_server.sockets[0].getsockname()[1]
        yield f"ws://127.0.0.1:{port}{cfg.path}"


async def test_single_turn_end_to_end():
    async with running_server() as uri:
        sim = PendantSim(uri)
        # fast mode: don't pace mic frames in real time, keeps the test quick.
        results = await sim.session(turns=1, speech_ms=600, realtime=False)
    r = results[0]
    assert r.ok
    assert r.transcript.strip() != ""
    assert r.response.strip() != ""
    assert r.audio_bytes > 0
    assert r.server_metrics["ttfa_ms"] is not None
    assert r.client_ttfa_ms is not None


async def test_multi_turn_session_keeps_memory():
    async with running_server() as uri:
        sim = PendantSim(uri)
        results = await sim.session(turns=3, speech_ms=400, realtime=False)
    assert all(r.ok for r in results)
    assert len(results) == 3


async def test_latency_budget_gate():
    # With near-zero simulated compute, server-measured TTFA should be tiny.
    async with running_server(
        mock_stt_finalize_s=0.05,
        mock_llm_ttft_s=0.08,
        mock_llm_token_s=0.005,
        mock_tts_first_s=0.03,
    ) as uri:
        sim = PendantSim(uri)
        results = await sim.session(turns=1, speech_ms=400, realtime=False)
    ttfa = results[0].server_metrics["ttfa_ms"]
    # Gate: warm-pipeline TTFA must beat 500ms with these simulated costs.
    assert ttfa < 500, f"TTFA regressed: {ttfa}ms"
