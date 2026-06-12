# Hardware bring-up checklist

The order here mirrors the design doc's build phases, with a **gate** at each
step so you never carry a broken layer forward. Software is already proven via
the simulator and stress tests; this is about marrying it to the physical
necklace.

## 0. Parts (see the BOM in `../docs/screenless-pendant-v1-spec.md`)

- Seeed XIAO ESP32-S3 **Sense** (onboard PDM mic) + U.FL antenna
- MAX98357A I2S amp + 20 mm 8 Ω speaker
- Tactile button, 500 mAh LiPo, JST lead
- 3D-printed shell (mic-up / button-front / USB-C-down), breakaway cord

## 1. Flash + Wi-Fi smoke test
- Set `WIFI_SSID`, `WIFI_PASSWORD`, `SERVER_HOST`, `SERVER_PORT` in
  `firmware/pendant-esp32s3/src/config.h`.
- `cd firmware/pendant-esp32s3 && pio run -t upload && pio device monitor`.
- **Gate:** board associates with Wi-Fi and the serial log shows the WebSocket
  reaching `ready`. RTT (`ping`/`pong`) under ~50 ms on the same LAN.

## 2. Mic capture
- Hold the button; the firmware streams 40 ms PCM frames.
- Run the server with `PENDANT_TTS=mock` and watch `partial`/`final` land.
- **Gate:** clean audio, no I2S underruns in the serial log; transcript is
  sane once the real Whisper backend is on (step 5).

## 3. Streaming loop with mocks (do this BEFORE the real models)
- Run the server with all-mock backends (the default).
- Press-hold-release on the pendant; confirm you get `say` text and binary
  audio frames back, and the amp makes sound.
- **Gate:** full press→release→audio loop works on the necklace with mocks.
  TTFA in the `done` metrics under ~150 ms on-LAN with mocks.

## 4. Swap in the real models (Mac mini)
- `export PENDANT_STT=whisper PENDANT_LLM=ollama PENDANT_TTS=piper` (see
  `README.md`), start Ollama, pull the model.
- **Gate:** real transcription + spoken answer. Warm-pipeline **TTFA ≤ 1.0 s**
  for a short reply (≤ 1.5 s for the briefing). If it regresses, the first
  suspect is a cold model load — confirm everything is resident.

## 5. Barge-in + LED states
- Press during playback: confirm `cancel` aborts the current answer and the
  new turn starts. Verify LED legend (off / breathing / slow-blink /
  double-blink) against `firmware/.../README.md`.
- **Gate:** interruption cancels audio in well under ~150 ms.

## 6. Necklace assembly + wear test
- Mount board + amp + speaker + 500 mAh cell + U.FL antenna in the shell.
- **Route the U.FL antenna up toward the lanyard loop, away from the body** —
  this is the difference between whole-home Wi-Fi and dropouts (design doc A.5).
- **Gate:** worn on the body, Wi-Fi holds across the house; ~3–4 h continuous /
  all-day intermittent runtime on push-to-talk; pendant ≤ ~30 g and comfortable.

## 7. The briefing
- Wire the LLM step to the ad-free feed backend so "what's my morning brief"
  returns a real synthesized summary.
- **Gate:** briefing TTFA ≤ 1.5 s end to end.

---

### Soak / regression before each hardware session
Run the load benchmark to confirm the server hasn't regressed:

```bash
python3 scripts/bench.py --pendants 20 --turns 5 --profile realistic
```

A green `latency gate` line means the warm pipeline still meets budget under
load before you plug in the hardware.
