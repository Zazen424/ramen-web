# Screenless AI Pendant — v1 Design & Architecture

Companion to [`screenless-pendant-v1-spec.md`](./screenless-pendant-v1-spec.md). The spec answers *what parts and why*; this doc answers *how it's worn* and *how it stays fast*.

Two design pillars drive every decision here:

1. **Necklace-first.** It has to be a thing you'd actually wear all day — light, balanced, silent, and safe to yank off.
2. **Fast.** Push the button, talk, release — and hear the answer before you'd have unlocked a phone. The target is **answer audio starting in under ~1 second** after you stop talking.

---

## Part A — The necklace (physical design)

### A.1 How it hangs

```
            ╭─── breakaway magnetic clasp (safety + easy on/off)
            │
   ───●─────┴─────●───    cord / chain (paracord, leather, or chain)
            │
            │  ~ adjustable 55–70 cm loop → pendant sits at sternum
            │
        ┌───┴───┐
        │  ▢ ▢  │   ← LED status window (top) + PDM mic port (top edge, faces up toward mouth)
        │       │
        │  ( ● ) │   ← push-to-talk button (front face, thumb-reachable)
        │       │
        └───┬───┘
            │  ← USB-C charge port (bottom edge, faces down so it stays clean)
```

- **Mic faces up.** The PDM port sits on the top edge so it points toward your mouth, not your chest. This alone is worth a few dB of SNR and shorter, cleaner audio for the STT stage.
- **Button on the front face**, slightly proud of the shell, so it's findable by thumb without looking. Push-to-talk is a deliberate, single-handed gesture.
- **USB-C on the bottom edge**, pointing down — keeps lint/sweat out and lets you charge it hanging on a hook.
- **LED window up top**, visible to *you* when you glance down and to *others* as a recording-state tell (consent signaling, see A.4).

### A.2 Comfort & weight budget

The whole point of a necklace is that you forget it's there. Target **≤ 30 g** all-in.

| Component | Mass (approx.) |
| --- | --- |
| XIAO ESP32-S3 Sense | ~3.5 g |
| 500 mAh LiPo | ~9 g |
| Enclosure (PETG/resin, ~1.6 mm walls) | ~10 g |
| Button, U.FL pigtail, wiring | ~3 g |
| Cord + clasp | ~4 g |
| **Total** | **~30 g** |

Notes:
- **PETG or resin over PLA** — PLA creeps and goes soft against body heat over a long day; PETG and resin hold shape and shrug off sweat.
- **Round every edge.** A pendant rests against skin and clothing constantly; sharp corners catch fabric and annoy.
- **Center of mass low and flat** so it lies against the chest instead of tumbling face-out.

### A.3 The cord & the breakaway clasp (safety, non-negotiable)

Anything worn as a closed loop around the neck **must** fail open under load. Use a **magnetic breakaway clasp** (the kind on baby/medical lanyards): it holds for normal wear and pops apart if it snags or someone pulls it. This is a safety requirement, not a convenience.

- Cord is **user-swappable** (paracord, leather, or chain) — the clasp and a small cord channel in the shell are the only fixed parts.
- Adjustable length, **55–70 cm loop**, lands the pendant at the sternum for most adults.

### A.4 Status LED — privacy as a feature

A single addressable LED (the XIAO's onboard user LED is fine for v1) does triple duty:

| State | LED | Meaning |
| --- | --- | --- |
| Idle / deep sleep | off | Mic is **not** capturing. The default. |
| Capturing & streaming | solid / breathing | "I'm listening right now" — for you *and* anyone nearby. |
| Connecting / reconnecting Wi-Fi | slow blink | transient |
| Error (no server, low battery) | double-blink | needs attention |

Because the radio and mic only wake on a button hold (see [spec §3](./screenless-pendant-v1-spec.md)), "LED off = not recording" is a hardware-honest promise, not a software one. That's the consent story.

### A.5 Enclosure design rules

- **Two-piece shell**, ultrasonic-weld-free: friction-fit lip + two M1.4 screws or a captive snap, so you can re-open it to swap the battery.
- **Mic acoustic port:** a single ~1 mm hole over the PDM mic, backed with a thin hydrophobic mesh (PTFE) to keep sweat out without muffling.
- **Light pipe** for the LED — a 2 mm clear filament/resin plug or just a thin translucent wall section.
- **Strain relief** on the USB-C and battery solder pads — the most common failure point on wearables is a flexed wire. Add a glue fillet or a printed clamp.
- Start from the **OpenGlass / Omi STLs** ([spec §7](./screenless-pendant-v1-spec.md)) and remix the mic-up, button-front layout above.

---

## Part B — Fast: the low-latency architecture

### B.1 What "fast" means (the latency budget)

The metric that matters is **time-to-first-audio (TTFA)**: from the instant you *release* the button to the first sound of the answer. People perceive a response as "instant" under ~300 ms and "snappy" under ~1 s. With local models on a Mac mini, the realistic, honest v1 target is:

> **TTFA ≤ 1.0 s** for a short reply, **≤ 1.5 s** for the morning briefing.

The enabling trick is that **nothing waits for the whole previous stage to finish.** Audio, transcript tokens, LLM tokens, and TTS audio all *stream* and *overlap*. The budget below assumes that pipelining:

| Stage | What happens | Budget (warm) |
| --- | --- | --- |
| Capture → release | audio already streamed *while you spoke* | 0 ms incremental |
| Network flush | last ~40 ms frame lands on the Mac mini | ~20–50 ms |
| STT finalize | Whisper finalizes the tail (most was transcribed live) | ~150–300 ms |
| LLM first token | warm model emits first token | ~150–400 ms |
| First sentence → TTS | Piper synthesizes sentence #1 | ~100–200 ms |
| Playback start | CoreAudio buffer | ~20–50 ms |
| **TTFA total** | | **~0.5–1.0 s** |

The killers we design *out*: cold model loads, per-utterance Wi-Fi reconnects, waiting for end-of-utterance via silence detection, resampling, and running stages strictly back-to-back.

### B.2 The seven rules that make it fast

1. **Push-to-talk is the endpoint.** Button-release is an explicit, zero-latency end-of-speech signal. We do **not** wait on VAD/silence timeouts to decide you're done — that alone saves the 300–700 ms most assistants burn on endpointing.
2. **Stream while the button is held.** The pendant sends 20–40 ms audio frames continuously during the hold. By release, ~95% of your speech is already transcribed; only the tail remains.
3. **Keep the socket warm.** One persistent WebSocket, opened on wake and held with cheap keep-alive pings. No TLS handshake or reconnect on the hot path.
4. **Keep every model warm.** Whisper, the LLM (Ollama `keep_alive: -1`), and Piper stay resident in RAM/VRAM. A cold model load is 1–5 s — unacceptable on the hot path, so it never happens there.
5. **Overlap the pipeline.** STT → LLM → TTS run as async stages joined by queues. The LLM starts on the *final* transcript; TTS starts on the LLM's *first sentence*; playback starts on TTS's *first chunk*. First audio leaves before the LLM has finished thinking.
6. **Right-size and accelerate the models.** Small, quantized, Metal-accelerated models tuned for latency over peak quality (see B.5). A 3B LLM that answers in 400 ms beats a 14B that answers in 4 s for this use case.
7. **No needless conversion.** Capture at **16 kHz mono PCM16** — exactly what Whisper wants — so there's zero resampling between mic and model. Send raw PCM (or Opus only if Wi-Fi range forces it; see B.6).

### B.3 End-to-end data flow

```
PENDANT (ESP32-S3)                     MAC MINI (async Python server)
─────────────────                      ─────────────────────────────
button DOWN
  └─ wake radio + mic (already warm)
  └─ open/resume persistent WebSocket ───────► [Connection Mgr]
                                                   │ session opened
  └─ PDM → I2S DMA, 16 kHz mono                    ▼
  └─ 40 ms PCM frames  ───stream──────────►  [Audio Ingest ring buffer]
        (continuous while held)                    │ frames
                                                    ▼
                                            [STT: faster-whisper, warm]
                                              streaming partial transcripts
button UP
  └─ send END marker  ───────────────────►  finalize transcript (tail only)
                                                    │ final text
                                                    ▼
                                            [LLM: Ollama, warm, streaming]
                                              tokens ──► [Sentence splitter]
                                                    │ sentence #1, #2, …
                                                    ▼
                                            [TTS: Piper, streaming]
                                              audio chunks
                                                    ▼
                                            [Playback: CoreAudio / sounddevice]
                                              ► Mac mini speaker (or BT)
  LED: solid while held ──► off on release        (pendant is input-only, v1)
```

Stages are connected by `asyncio` queues; each runs concurrently. The first TTS chunk hits the speaker while the LLM is still generating later sentences.

### B.4 Mac mini server — module breakdown

A single async Python process (`asyncio` + `websockets`), one task per stage:

- **Connection Manager** — `websockets` server, one session per pendant. Holds the socket open, answers keep-alive pings, tags frames with a session id. Handles reconnect transparently so a brief Wi-Fi blip doesn't drop a turn.
- **Audio Ingest** — fixed-size ring buffer fed by incoming frames; exposes a stream to the STT worker. Backpressure-aware so a slow consumer never balloons memory.
- **STT Worker** — `faster-whisper` (CTranslate2) running `small`/`distil-small.en` on Metal, in streaming mode. Emits partial transcripts as audio arrives; finalizes on the END marker.
- **LLM Worker** — Ollama client, **streaming** completions, `keep_alive: -1` so the model never unloads. A short system prompt and a sentence splitter that flushes complete sentences downstream the instant a clause boundary appears.
- **TTS Worker** — Piper, fed sentence-by-sentence, emitting PCM chunks as each sentence synthesizes. (XTTS is the higher-quality, higher-latency upgrade path — keep it behind a config flag.)
- **Playback** — `sounddevice`/CoreAudio output stream on the Mac mini; plays chunks as they arrive. Supports **barge-in**: a new button-down cancels in-flight LLM/TTS and playback, so you can interrupt.
- **Orchestrator** — wires the queues, owns the per-turn lifecycle (start → stream → finalize → respond → idle), enforces timeouts, and emits the cancel signal for barge-in.

A `--echo` mode short-circuits LLM+TTS and just speaks the transcript back — the [spec §5 step 4](./screenless-pendant-v1-spec.md) sanity check.

### B.5 Model choices (latency-tuned defaults)

| Stage | Default (fast) | Quality upgrade | Why the default |
| --- | --- | --- | --- |
| STT | `distil-small.en` / `small` via faster-whisper, Metal | `medium` / `large-v3-turbo` | distil + CT2 on Metal finalizes a short utterance in a few hundred ms |
| LLM | Llama 3.2 3B or Qwen 2.5 3B, Q4, via Ollama | 8B/14B | 3B at Q4 streams first token in ~150–400 ms warm |
| TTS | Piper (medium voice) | XTTS-v2 | Piper is near-real-time on CPU; no GPU contention with STT/LLM |

All three stay **resident**. On server start they're pre-warmed with a dummy inference so the first *real* turn isn't paying a cold-start tax.

### B.6 Transport & firmware notes for speed

- **Frame size 20–40 ms.** Small enough to keep buffering latency low, large enough to avoid per-packet Wi-Fi overhead. 40 ms of 16 kHz mono PCM16 = 1280 bytes — one tidy frame.
- **Raw PCM by default.** It costs the ESP32 nothing to encode and Whisper nothing to decode. Only switch to **Opus** if real-world Wi-Fi range/contention forces lower bandwidth — Opus cuts bytes ~10× at the cost of a few ms encode/decode each way.
- **Warm Wi-Fi.** Keep the STA connection up while the session socket is open; only drop to deep sleep after an idle timeout. Reconnecting Wi-Fi from cold is ~1–2 s — far too slow for the hot path, so the first button press after a long idle eats that, not every press.
- **DMA capture.** PDM → I2S with DMA double-buffering so the CPU just hands off filled buffers — no sample-by-sample copying, no dropped frames.
- **Firmware state machine:** `DEEP_SLEEP → (button) WAKE → CONNECT/RESUME → STREAM → (release) FLUSH+END → IDLE → (timeout) DEEP_SLEEP`. The LED mirrors these states (A.4).

### B.7 Honest latency caveats

- **First press after long idle is slower** (~1–2 s extra) because Wi-Fi was asleep. That's the deliberate power/latency trade from [spec §3](./screenless-pendant-v1-spec.md). Frequent use keeps the radio warm and the loop sub-second.
- **The briefing is longer** because its *answer* is longer to synthesize — but TTFA is still ~1–1.5 s since we start speaking sentence #1 while the rest renders.
- **Mac mini contention.** STT, LLM, and TTS share the machine. The 3B/distil/Piper defaults are chosen so all three fit in memory and don't thrash. Bigger models are a quality-vs-latency dial, not a free upgrade.

---

## Part C — Build order delta (fast loop)

This refines [spec §5](./screenless-pendant-v1-spec.md) with the latency work folded in:

1. **Warm socket smoke test.** Persistent WebSocket pendant ↔ Mac mini with keep-alive; measure round-trip ping. *Gate: < 50 ms RTT on the same LAN.*
2. **Streaming capture.** PDM → 40 ms PCM frames → server writes WAV. Verify no dropped frames at sustained stream. *Gate: clean audio, no underruns.*
3. **Streaming STT.** faster-whisper warm, partial transcripts during hold, finalize on END. *Gate: finalize ≤ 300 ms after release for a 3 s utterance.*
4. **Overlapped LLM + TTS.** Ollama streaming → sentence splitter → Piper streaming → playback. *Gate: TTFA ≤ 1.0 s warm.*
5. **Barge-in + LED states.** New press cancels in-flight response; LED tracks state. *Gate: interrupt cancels audio in < 150 ms.*
6. **Necklace build.** Print mic-up/button-front shell, breakaway cord, 500 mAh cell; wear-test comfort, range, and runtime.
7. **The briefing.** Wire the LLM step to the ad-free feed backend; "what's my morning brief" returns a synthesized summary with TTFA ≤ 1.5 s.

Each step has a **latency gate** — if it regresses past the gate, fix it before moving on. Speed is the feature; it doesn't get bolted on at the end.
