#!/usr/bin/env python3
"""Latency + load benchmark for the pendant server.

Spins up an in-process server with mock backends and drives it with N
concurrent simulated pendants doing T turns each, then prints a latency
report (TTFA percentiles, stage breakdown, throughput). Use it to catch
latency regressions and to sanity-check capacity before a hardware session.

    python3 scripts/bench.py --pendants 20 --turns 5
"""

from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "server"))
sys.path.insert(0, os.path.join(HERE, "..", "simulator"))

import websockets  # noqa: E402

from pendant_server.config import Config  # noqa: E402
from pendant_server.server import PendantServer  # noqa: E402
from pendant_sim import PendantSim  # noqa: E402


def _pct(values, p):
    if not values:
        return float("nan")
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((p / 100.0) * len(s) + 0.5)) - 1))
    return s[k]


async def run(pendants: int, turns: int, speech_ms: int, profile: str) -> int:
    presets = {
        "fast": dict(mock_stt_finalize_s=0.02, mock_llm_ttft_s=0.03,
                     mock_llm_token_s=0.002, mock_tts_first_s=0.02),
        "realistic": dict(mock_stt_finalize_s=0.10, mock_llm_ttft_s=0.15,
                          mock_llm_token_s=0.010, mock_tts_first_s=0.05),
    }
    cfg = Config(host="127.0.0.1", port=0, **presets[profile])
    srv = PendantServer(cfg)
    await srv.prewarm()

    async with websockets.serve(srv.handler, cfg.host, 0, max_size=None) as ws_server:
        port = ws_server.sockets[0].getsockname()[1]
        uri = f"ws://127.0.0.1:{port}{cfg.path}"

        async def one():
            return await PendantSim(uri).session(turns=turns, speech_ms=speech_ms, realtime=False)

        t0 = time.perf_counter()
        batches = await asyncio.gather(*[one() for _ in range(pendants)])
        wall = time.perf_counter() - t0

    flat = [r for b in batches for r in b]
    ok = [r for r in flat if r.ok]
    ttfa = [r.server_metrics["ttfa_ms"] for r in ok]
    asr = [r.server_metrics["asr_final_ms"] for r in ok if r.server_metrics.get("asr_final_ms") is not None]
    llm = [r.server_metrics["llm_ttft_ms"] for r in ok if r.server_metrics.get("llm_ttft_ms") is not None]
    total = [r.server_metrics["total_ms"] for r in ok if r.server_metrics.get("total_ms") is not None]

    print(f"\n=== pendant server benchmark ({profile} profile) ===")
    print(f"pendants={pendants}  turns/pendant={turns}  total turns={len(flat)}  ok={len(ok)}")
    print(f"wall clock: {wall*1000:.0f} ms   throughput: {len(flat)/wall:.1f} turns/s")
    print(f"\nTTFA (endpoint -> first audio), ms:")
    print(f"  min {min(ttfa):.0f}  mean {statistics.mean(ttfa):.0f}  "
          f"p50 {_pct(ttfa,50):.0f}  p95 {_pct(ttfa,95):.0f}  max {max(ttfa):.0f}")
    print(f"stage means: asr_final {statistics.mean(asr):.0f}  "
          f"llm_ttft {statistics.mean(llm):.0f}  total {statistics.mean(total):.0f}")

    bad = [r for r in flat if not r.ok]
    if bad:
        print(f"\n!! {len(bad)} turns FAILED")
        return 1
    # Honest gate matching the design budget for the fast profile.
    gate = 500 if profile == "fast" else 1500
    p95 = _pct(ttfa, 95)
    status = "PASS" if p95 < gate else "FAIL"
    print(f"\nlatency gate: p95 TTFA {p95:.0f}ms < {gate}ms  -> {status}")
    return 0 if status == "PASS" else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pendants", type=int, default=20)
    ap.add_argument("--turns", type=int, default=5)
    ap.add_argument("--speech-ms", type=int, default=400)
    ap.add_argument("--profile", choices=["fast", "realistic"], default="fast")
    args = ap.parse_args()
    return asyncio.run(run(args.pendants, args.turns, args.speech_ms, args.profile))


if __name__ == "__main__":
    raise SystemExit(main())
