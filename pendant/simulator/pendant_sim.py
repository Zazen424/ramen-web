"""Software pendant: a real WebSocket client that speaks the wire protocol.

Stands in for the ESP32 firmware so the whole loop can be exercised, measured,
and stress tested without hardware. It streams synthetic mic frames at
real-time pace, signals the button-release endpoint, collects the downlink
audio, and reports the server-measured TTFA alongside its own wall-clock view.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import struct
import time
from dataclasses import dataclass, field
from typing import List, Optional

import websockets

# Allow running as a script from anywhere by importing the protocol constants.
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
from pendant_server import protocol as P  # noqa: E402


def _silence_frame() -> bytes:
    return b"\x00\x00" * P.FRAME_SAMPLES


def _tone_frame(t0: float, freq: float = 200.0) -> bytes:
    buf = bytearray()
    step = 2 * math.pi * freq / P.SAMPLE_RATE
    phase = t0
    for _ in range(P.FRAME_SAMPLES):
        buf += struct.pack("<h", int(6000 * math.sin(phase)))
        phase += step
    return bytes(buf)


@dataclass
class TurnResult:
    turn: int
    transcript: str = ""
    response: str = ""
    server_metrics: dict = field(default_factory=dict)
    client_ttfa_ms: Optional[float] = None
    audio_bytes: int = 0
    ok: bool = False


class PendantSim:
    def __init__(self, uri: str) -> None:
        self.uri = uri

    async def run_turn(self, ws, turn: int, speech_ms: int = 1200, realtime: bool = True) -> TurnResult:
        res = TurnResult(turn=turn)
        await ws.send(P.encode(P.start(turn)))

        # Stream mic frames for the duration of "speech".
        n_frames = max(1, speech_ms // P.FRAME_MS)
        phase = 0.0
        for _ in range(n_frames):
            await ws.send(_tone_frame(phase))
            phase += 2 * math.pi * 200.0 / P.SAMPLE_RATE * P.FRAME_SAMPLES
            if realtime:
                await asyncio.sleep(P.FRAME_MS / 1000.0)

        # Button release == endpoint. Start the client-side TTFA clock here.
        t_end = time.perf_counter()
        await ws.send(P.encode(P.end(turn)))

        # Collect responses until 'done'.
        got_first_audio = False
        while True:
            msg = await ws.recv()
            if isinstance(msg, (bytes, bytearray)):
                res.audio_bytes += len(msg)
                if not got_first_audio:
                    got_first_audio = True
                    res.client_ttfa_ms = round((time.perf_counter() - t_end) * 1000.0, 1)
                continue
            obj = P.decode(msg)
            t = obj.get("t")
            if t == P.FINAL:
                res.transcript = obj.get("text", "")
            elif t == P.SAY:
                res.response = (res.response + " " + obj.get("text", "")).strip()
            elif t == P.DONE:
                res.server_metrics = obj.get("metrics", {})
                res.ok = True
                break
            elif t == P.ERROR:
                res.response = f"[error] {obj.get('msg')}"
                break
        return res

    async def session(self, turns: int = 1, speech_ms: int = 1200, realtime: bool = True) -> List[TurnResult]:
        results: List[TurnResult] = []
        async with websockets.connect(self.uri, max_size=None) as ws:
            await ws.send(P.encode(P.hello()))
            ready = P.decode(await ws.recv())
            assert ready.get("t") == P.READY, ready
            for i in range(1, turns + 1):
                results.append(await self.run_turn(ws, i, speech_ms, realtime))
        return results


async def _main() -> None:
    ap = argparse.ArgumentParser(description="Software pendant simulator")
    ap.add_argument("--uri", default="ws://127.0.0.1:8765/pendant")
    ap.add_argument("--turns", type=int, default=1)
    ap.add_argument("--speech-ms", type=int, default=1200)
    ap.add_argument("--fast", action="store_true", help="don't pace mic frames in real time")
    args = ap.parse_args()

    sim = PendantSim(args.uri)
    results = await sim.session(args.turns, args.speech_ms, realtime=not args.fast)
    for r in results:
        m = r.server_metrics
        print(f"turn {r.turn}: ok={r.ok}")
        print(f"  transcript : {r.transcript!r}")
        print(f"  response   : {r.response!r}")
        print(f"  audio      : {r.audio_bytes} bytes")
        print(f"  client TTFA: {r.client_ttfa_ms} ms")
        print(f"  server     : ttfa={m.get('ttfa_ms')}ms asr_final={m.get('asr_final_ms')}ms "
              f"llm_ttft={m.get('llm_ttft_ms')}ms total={m.get('total_ms')}ms")


if __name__ == "__main__":
    asyncio.run(_main())
