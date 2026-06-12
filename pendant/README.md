# Screenless AI Pendant — working v1 implementation

A runnable, tested implementation of the low-latency voice loop described in
[`../docs/screenless-pendant-v1-design.md`](../docs/screenless-pendant-v1-design.md):

> Push the button, talk, release — hear the answer before you'd reach for a phone.

It has three parts:

| Part | Path | What it is |
| --- | --- | --- |
| **Server** | `server/` | Async Python orchestrator: warm, streaming, overlapped STT → LLM → TTS behind a WebSocket. Runs on the Mac mini. |
| **Firmware** | `firmware/pendant-esp32s3/` | PlatformIO project for the Seeed XIAO ESP32-S3 Sense: PDM capture, Wi-Fi/WebSocket streaming, I2S speaker playback, button, LED, deep sleep. |
| **Simulator** | `simulator/pendant_sim.py` | A software pendant that speaks the wire protocol — drives the server with no hardware, and is the load generator for the stress tests. |

The heavy models sit behind a swappable backend interface, so the **entire
pipeline runs and stress-tests anywhere** with deterministic mock backends.
On the Mac mini you flip three env vars to the real adapters — no
architecture change.

---

## Architecture (one paragraph)

A single async process holds the pendant's WebSocket open. Audio streams in as
40 ms PCM16 frames *while the button is held*; STT transcribes live and
finalizes the instant the button is released (a deterministic endpoint — no
VAD guesswork). The final transcript feeds a warm, streaming LLM whose tokens
are split into sentences on the fly; **sentence #1 is synthesized and streamed
back as audio before the LLM has finished generating the rest.** Every stage
is warm and persistent — nothing loads per request. The headline metric is
**TTFA** (time-to-first-audio): button-release → first sound.

```
button held → PDM mic → 40ms PCM frames ─WS─► [STT warm] ─final─► [LLM warm]
                                                                      │ tokens
button release = endpoint                              [sentence chunker]
                                                                      │ sentences
   pendant I2S speaker ◄─WS─ PCM chunks ◄──────────────────────── [TTS warm]
```

See `server/pendant_server/protocol.py` for the exact wire protocol shared by
the firmware and the server.

---

## Quick start (no hardware)

```bash
cd pendant
python3 -m pip install -r server/requirements.txt   # websockets + numpy

# Terminal 1 — run the server (mock backends by default)
PYTHONPATH=server python3 -m pendant_server

# Terminal 2 — drive it with the software pendant
PYTHONPATH=server python3 simulator/pendant_sim.py --turns 3
```

You'll see the transcript, the spoken response text, the audio byte count, and
both client- and server-measured TTFA per turn.

## Tests & benchmarks

```bash
cd pendant
python3 -m pip install -r server/requirements.txt pytest pytest-asyncio
python3 -m pytest                       # 23 tests: protocol, chunker, pipeline,
                                        # session/barge-in, e2e WS, stress

python3 scripts/bench.py --pendants 20 --turns 5 --profile fast
python3 scripts/bench.py --pendants 10 --turns 3 --profile realistic
```

The stress tests cover 25 concurrent pendants, 30 back-to-back turns, and a
barge-in storm, and assert latency-budget gates (not just "nothing crashed").

## Going live on the Mac mini

Install the real backends and point the env vars at them:

```bash
pip install faster-whisper aiohttp piper-tts      # + run Ollama separately
export PENDANT_STT=whisper  WHISPER_MODEL=distil-small.en
export PENDANT_LLM=ollama   OLLAMA_MODEL=qwen2.5:3b
export PENDANT_TTS=piper    PIPER_VOICE=en_US-amy-medium
PYTHONPATH=server python3 -m pendant_server
```

The orchestration, protocol, streaming, barge-in, and metrics are identical —
only the three backend objects change. See `HARDWARE.md` for the end-to-end
bring-up checklist with the physical pendant.

## Layout

```
pendant/
├── server/pendant_server/
│   ├── protocol.py        # wire protocol (shared source of truth)
│   ├── config.py          # env-driven config; backend selection
│   ├── pipeline.py        # the overlapped STT→LLM→TTS engine
│   ├── session.py         # per-connection turn lifecycle + barge-in + history
│   ├── server.py          # websockets wiring + prewarm
│   ├── sentence_chunker.py# incremental sentence splitter (LLM→TTS overlap)
│   ├── metrics.py         # per-turn latency accounting (TTFA)
│   └── backends/          # base ABCs, mock, whisper_stt, ollama_llm, piper_tts
├── simulator/pendant_sim.py
├── firmware/pendant-esp32s3/   # PlatformIO ESP32-S3 project
├── tests/                 # unit + integration + stress
├── scripts/bench.py       # latency + load benchmark
└── HARDWARE.md            # bring-up checklist
```
