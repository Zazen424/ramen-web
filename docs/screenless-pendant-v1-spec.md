# Screenless AI Pendant — v1 Hardware Spec

**Form factor:** Neck-worn pendant on a breakaway necklace cord, worn at sternum height
**Connectivity:** Wi-Fi → local server (Mac mini), phone-free
**Board:** Seeed XIAO ESP32-S3 Sense
**Goal of v1:** Capture voice on demand, stream to the Mac mini over Wi-Fi, get a *fast* synthesized response back. Nail a low-latency wake-up briefing loop before adding anything else.

> **Design intent:** A real necklace you'd wear all day — light, quiet, and quick. The two things v1 is judged on are **comfort** (it disappears around your neck) and **speed** (it answers before you'd reach for a phone). The full physical-design and low-latency architecture lives in [`screenless-pendant-v1-design.md`](./screenless-pendant-v1-design.md).

---

## 1. Why this board

The XIAO ESP32-S3 Sense is the right v1 endpoint because it does everything the pendant needs in a thumb-sized package and nothing it doesn't:

- **Wi-Fi 2.4 GHz + BLE 5.0** — talks to the Mac mini directly, no phone bridge.
- **Onboard PDM digital microphone** — no separate mic board for v1.
- **8 MB PSRAM / 8 MB Flash** — enough headroom for audio buffering and on-device wake word later.
- **Built-in LiPo charge management** — solder a battery to two pads, done.
- **21 × 17.5 mm** — genuinely wearable; this is the same board the OpenGlass project uses.
- **U.FL antenna connector** — needed for usable Wi-Fi range; the onboard trace antenna is weak.

It is **input-only** in v1. The pendant captures and streams; the *response* plays on the Mac mini's speaker (or a cheap BT speaker). Adding a speaker + amp to the pendant is a v2 decision — it costs size, power, and complexity, and you don't need it to prove the loop works.

---

## 2. Bill of materials (v1)

| Part | Spec | Approx. cost | Notes |
| --- | --- | --- | --- |
| Seeed XIAO ESP32-S3 **Sense** | dual-core LX7, Wi-Fi/BLE, PDM mic, 8MB PSRAM | ~$24 | Buy direct from Seeed; resellers mark it up to $50+ |
| U.FL Wi-Fi antenna | 2.4 GHz, comes with Sense kit | included | Required — don't skip it |
| LiPo battery | 3.7 V, **500 mAh** recommended | ~$6 | 250 mAh is smaller but ~2 h streaming; 500 mAh ~3–4 h |
| Tactile button | momentary, normally-open | ~$1 | Push-to-talk for v1 |
| 3D-printed enclosure | OpenGlass / Omi STLs fit XIAO | ~$2 filament | Open-source, remix to taste |
| JST connector + wire | for battery | ~$2 | Or solder battery leads straight to +/- pads |

**Total: ~$35–40.** Matches the "super cheap" goal.

---

## 3. The power reality (read this before you build)

Continuous Wi-Fi audio streaming is the battery killer. Real numbers:

- Board active, no camera: ~0.45 W ≈ **~120 mA** at 3.7 V.
- 250 mAh battery → **~2 hours** continuous streaming.
- 500 mAh battery → **~3–4 hours** continuous streaming.
- Deep sleep: **14 µA** (effectively forever).

The OpenGlass "11.8 hours" figure you may have seen is for *periodic photo capture* with the radio mostly asleep — not continuous audio. Don't design around it.

**The fix — duty-cycle the radio.** Two options, both of which also fix the "recording everyone around me" consent problem:

1. **Push-to-talk (v1):** Wi-Fi + mic only stream while the button is held. Average draw drops to near-deep-sleep between presses → a 500 mAh cell easily lasts a full day of intermittent use. Simplest, most reliable, most private. **Start here.**
2. **On-device wake word (v1.5):** ESP-SR / microWakeWord runs the wake-word model on the ESP32-S3 itself; it only opens the Wi-Fi stream after it hears your trigger phrase. More natural, slightly more power than push-to-talk, and keeps audio on-device until you summon it.

Avoid always-on 24/7 streaming entirely. It's bad for battery, bad for privacy, and unnecessary.

---

## 4. Architecture (v1)

```
[ Pendant: XIAO ESP32-S3 Sense ]
   button held → PDM mic captures audio
   → Wi-Fi (WebSocket/TCP) stream
            │
            ▼
[ Mac mini: local Python server ]
   VAD trims silence
   → Whisper (STT)
   → local LLM (Ollama) for reasoning / summary
   → TTS (Piper / XTTS)
            │
            ▼
   audio response plays on Mac mini speaker
   (or paired BT speaker)  ← pendant is input-only in v1
```

The pendant is deliberately dumb. All intelligence — transcription, the ad-free feed summary, GUI agent actions — lives on the Mac mini. That keeps the wearable cheap, low-power, and replaceable.

---

## 5. Build order

1. **Flash + Wi-Fi smoke test.** Get the XIAO on your network, confirm it reaches the Mac mini.
2. **Mic capture → file.** Record from the PDM mic, save a WAV locally, verify audio quality.
3. **Stream audio over Wi-Fi.** Button-held → WebSocket stream → server writes the WAV. This is the core plumbing.
4. **Server loop.** Whisper transcribes → echo the text back (sanity check) → then wire Ollama + Piper.
5. **Enclosure + battery.** Print a case, solder the 500 mAh cell, wear-test the range and runtime.
6. **Add the briefing.** Hook the server's LLM step to the ad-free feed backend (separate build) so "what's my morning brief" returns a real synthesized summary.

---

## 6. Known v1 limitations (deliberate, not bugs)

- **Wi-Fi only.** Works at home and on saved networks; goes dark elsewhere. "Go anywhere" needs cellular or a hotspot — a much bigger problem, deferred on purpose.
- **Input-only pendant.** Responses play on the Mac mini. Pendant-side audio out is v2.
- **~3–4 h continuous / all-day intermittent.** Push-to-talk makes the runtime livable; continuous streaming does not.
- **Range ~ up to 100 m with the U.FL antenna**, less through walls. It's a home-and-known-networks device first.

---

## 7. Open-source references to pull from

- **OpenGlass** — XIAO ESP32-S3 firmware + enclosure STLs (closest hardware match).
- **Omi (Based Hardware)** — pendant firmware/app patterns; note their current DevKit 2 moved to nRF5340, but the older XIAO-based design is the reference for this Wi-Fi build.
- **Willow** — ESP32-S3 audio pipeline and on-device wake-word reference (targets the BOX-3, but the audio/SR techniques transfer).
