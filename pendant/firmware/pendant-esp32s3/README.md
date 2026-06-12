# AI Voice Pendant — ESP32-S3 Firmware

Firmware for a screenless, push-to-talk AI voice pendant built on the
**Seeed Studio XIAO ESP32-S3 Sense**. It captures voice from the onboard PDM
microphone, streams it to a server over a WebSocket, and plays back the
returned TTS audio through a MAX98357A I2S amplifier and a small speaker.

```
DEEP_SLEEP --(button)--> WIFI_CONNECT --> WS_CONNECT --> IDLE
   ^                                                       |
   |                                              (button down)
   |                                                       v
   +-------- (idle timeout) <-- IDLE <-- PLAYBACK <-- STREAMING
```

- **Button DOWN** = start a turn (`start` + stream mic frames).
- **Button UP** = endpoint the turn (`end`).
- **Press during playback** = barge-in (`cancel` then a new `start`).
- Wi-Fi + WebSocket stay warm during a session; the pendant only deep-sleeps
  after an idle timeout (default **30 s**, see `IDLE_TIMEOUT_MS`).

---

## Hardware

- **MCU:** Seeed XIAO ESP32-S3 Sense (ESP32-S3 dual LX7, Wi-Fi 2.4 GHz, 8 MB PSRAM).
- **Microphone:** onboard PDM mic on the Sense expansion board (16 kHz mono PCM16 via I2S PDM-RX).
- **Speaker out:** MAX98357A I2S Class-D amp + 20 mm 8 Ω speaker.
- **Button:** momentary, normally-open, push-to-talk (to GND, internal pull-up).
- **LED:** onboard user LED (active-low).
- **Antenna:** U.FL external antenna.
- **Power:** 500 mAh LiPo via the XIAO's onboard charger.

### Wiring table

| Signal            | XIAO pad | GPIO    | Notes                                              |
|-------------------|----------|---------|----------------------------------------------------|
| PDM mic clock     | (onboard)| GPIO42  | Fixed by the Sense expansion board                 |
| PDM mic data      | (onboard)| GPIO41  | Fixed by the Sense expansion board                 |
| Amp **BCLK**      | D1       | GPIO2   | MAX98357A bit clock                                |
| Amp **LRCLK (WS)**| D2       | GPIO3   | MAX98357A word/left-right clock                    |
| Amp **DIN**       | D3       | GPIO4   | MAX98357A serial data in                           |
| Button            | D0       | GPIO1   | To GND; internal pull-up; RTC-capable (ext0 wake)  |
| Status LED        | (onboard)| GPIO21  | Onboard user LED, **active-low**                   |

**MAX98357A extra pins (hardware, not driven by firmware):**

| MAX98357A pin | Connect to                                                            |
|---------------|-----------------------------------------------------------------------|
| VIN           | 3V3 (or battery 3.0–5 V; 3V3 from XIAO is fine for low volume)         |
| GND           | GND                                                                   |
| SD (shutdown) | Leave floating or tie to VIN through ~100 kΩ to keep the amp enabled.  |
| GAIN          | Leave floating for the default **9 dB** gain. Tie to GND/VIN to change.|
| OUT+ / OUT−   | Speaker (8 Ω). **Do not ground OUT−** — it is a bridge-tied output.    |

> The mic (I2S0, PDM-RX) and the amp (I2S1, standard TX) use **separate I2S
> peripherals**, so capture and playback can run independently.

---

## Build & flash

Requires [PlatformIO](https://platformio.org/).

```bash
cd pendant/firmware/pendant-esp32s3

pio run                 # compile
pio run -t upload       # compile + flash over USB-C
pio device monitor      # serial console @115200
```

Libraries (`links2004/WebSockets`, `bblanchon/ArduinoJson`) are pulled
automatically from `platformio.ini`. PSRAM (octal/OPI) is enabled there via
`board_build.arduino.memory_type = qio_opi` + `-DBOARD_HAS_PSRAM`.

---

## Configuration

All knobs live in **`src/config.h`**.

1. **Wi-Fi** — set `WIFI_SSID` / `WIFI_PASSWORD`.
2. **Server** — set `SERVER_HOST`, `SERVER_PORT` (default `8765`),
   `SERVER_PATH` (default `/pendant`). The pendant connects to
   `ws://<host>:<port><path>`.
3. **Idle timeout** — `IDLE_TIMEOUT_MS` (default 30000).
4. **Pins** — already set for the XIAO Sense; change here if you rewire.

---

## WebSocket wire protocol

Transport: WebSocket client → `ws://<server>:8765/pendant`.

- **TEXT** frames = JSON control (ArduinoJson).
- **BINARY** frames = raw little-endian PCM16 @ 16 kHz mono.
- Mic frames are 40 ms = 640 samples = **1280 bytes** PCM16LE.

**Pendant → Server (TEXT):**

```json
{"t":"hello","fw":"1.0","sr":16000,"fmt":"pcm16"}
{"t":"start","turn":N}
{"t":"end","turn":N}
{"t":"cancel","turn":N}
{"t":"ping","ts":MS}
```

**Pendant → Server (BINARY):** mic PCM frames, only between `start` and `end`.

**Server → Pendant (TEXT):**
`ready`, `partial`, `final`, `say`, `audio_start`, `audio_end`, `done`,
`pong`, `error`.

**Server → Pendant (BINARY):** TTS PCM frames between `audio_start` and
`audio_end` — fed to the amp via a PSRAM ring buffer so playback starts as
chunks arrive.

---

## LED state legend

| LED pattern    | Meaning                          |
|----------------|----------------------------------|
| Off            | Idle / sleeping                  |
| Breathing      | Capturing (mic streaming)        |
| Slow blink     | Connecting (Wi-Fi / WebSocket)   |
| Double blink   | Error                            |

---

## Antenna routing note

The U.FL external antenna has **no firmware impact**, but placement matters for
range: **route the U.FL pigtail upward toward the lanyard loop, away from the
body.** Body tissue detunes and absorbs 2.4 GHz, so keeping the antenna near
the top of the enclosure (closest to open air when worn) gives the best Wi-Fi
link. Keep the antenna away from the LiPo and any ground planes.

---

## File layout

```
pendant/firmware/pendant-esp32s3/
├── platformio.ini      # board, framework, PSRAM, lib_deps
├── README.md           # this file
└── src/
    ├── config.h        # Wi-Fi/server/pins/audio/timeouts
    └── main.cpp        # state machine, Wi-Fi, WS, I2S in/out, button, LED, sleep
```
