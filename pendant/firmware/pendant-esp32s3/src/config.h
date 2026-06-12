// =============================================================================
// config.h — Compile-time configuration for the AI voice pendant.
//
// Board: Seeed Studio XIAO ESP32-S3 Sense.
// Everything that an integrator might want to tweak (Wi-Fi creds, server
// address, pin map, audio format, timeouts) lives here. The rest of the
// firmware treats these as fixed.
// =============================================================================
#pragma once

#include <Arduino.h>

// -----------------------------------------------------------------------------
// Wi-Fi credentials.  Replace with your network. (Kept here for simplicity;
// a real product would provision these at runtime / over BLE.)
// -----------------------------------------------------------------------------
#define WIFI_SSID       "YOUR_WIFI_SSID"
#define WIFI_PASSWORD   "YOUR_WIFI_PASSWORD"

// -----------------------------------------------------------------------------
// Signaling server.  The pendant connects to ws://<host>:<port><path>.
// -----------------------------------------------------------------------------
#define SERVER_HOST     "192.168.1.100"   // server LAN IP or hostname
#define SERVER_PORT     8765
#define SERVER_PATH     "/pendant"

// -----------------------------------------------------------------------------
// Audio format — MUST match the server's expectations.
//   16 kHz, mono, signed 16-bit little-endian PCM.
//   40 ms frame = 16000 * 0.040 = 640 samples = 1280 bytes.
// -----------------------------------------------------------------------------
static constexpr uint32_t SAMPLE_RATE_HZ   = 16000;
static constexpr uint32_t FRAME_MS         = 40;
static constexpr size_t   FRAME_SAMPLES    = (SAMPLE_RATE_HZ * FRAME_MS) / 1000; // 640
static constexpr size_t   FRAME_BYTES      = FRAME_SAMPLES * sizeof(int16_t);    // 1280

// -----------------------------------------------------------------------------
// Pin map.
//
// === XIAO ESP32-S3 Sense onboard PDM microphone ===
// The Sense expansion board wires the PDM mic to fixed GPIOs. These are the
// pins Seeed documents for the XIAO ESP32-S3 Sense:
//     PDM CLK  -> GPIO42
//     PDM DATA -> GPIO41
// We drive it through the ESP32 I2S peripheral in PDM-RX mode.
//
// === MAX98357A I2S Class-D amplifier (output) ===
// Wired to three free XIAO header pads. The MAX98357A needs BCLK, LRCLK (WS)
// and DIN. (SD/GAIN are tied off in hardware — see README.)
//     BCLK  -> GPIO2  (D1 pad)
//     LRCLK -> GPIO3  (D2 pad)  (a.k.a. WS / word-select)
//     DIN   -> GPIO4  (D3 pad)
//
// === Push-to-talk button ===
// Momentary, normally-open, to GND. Internal pull-up enabled, so the pin
// reads HIGH when idle and LOW when pressed. GPIO1 (D0 pad) is RTC-capable,
// which is required for ext0 deep-sleep wake.
//     BUTTON -> GPIO1 (D0 pad)
//
// === Status LED ===
// XIAO ESP32-S3 has an onboard user LED on GPIO21. It is ACTIVE-LOW
// (drive LOW = on).
//     LED -> GPIO21 (onboard, active-low)
// -----------------------------------------------------------------------------

// --- PDM microphone (I2S_NUM_0, RX) ---
static constexpr int PIN_PDM_CLK   = 42;
static constexpr int PIN_PDM_DATA  = 41;

// --- MAX98357A amplifier (I2S_NUM_1, TX) ---
static constexpr int PIN_AMP_BCLK  = 2;
static constexpr int PIN_AMP_LRCLK = 3;
static constexpr int PIN_AMP_DIN   = 4;

// --- Button ---
static constexpr gpio_num_t PIN_BUTTON = GPIO_NUM_1;   // RTC-capable for ext0 wake

// --- Status LED ---
static constexpr int  PIN_LED        = 21;
static constexpr bool LED_ACTIVE_LOW = true;

// -----------------------------------------------------------------------------
// Behavioral timing.
// -----------------------------------------------------------------------------
static constexpr uint32_t IDLE_TIMEOUT_MS   = 30000;  // go to deep sleep after this much idle
static constexpr uint32_t BUTTON_DEBOUNCE_MS = 25;    // debounce window
static constexpr uint32_t WS_PING_INTERVAL_MS = 5000; // app-level keepalive ping
static constexpr uint32_t WIFI_CONNECT_TIMEOUT_MS = 15000;

// WebSocket reconnect backoff (exponential, capped).
static constexpr uint32_t WS_BACKOFF_MIN_MS = 500;
static constexpr uint32_t WS_BACKOFF_MAX_MS = 8000;

// -----------------------------------------------------------------------------
// Audio buffers.
//   I2S DMA: double-buffered, dma_buf_len chosen so one DMA buffer ≈ one frame.
//   Playback ring buffer: a few hundred ms of PCM so playback can start as the
//   first chunks arrive without underrunning.
// -----------------------------------------------------------------------------
static constexpr int    I2S_DMA_BUF_COUNT = 4;
static constexpr int    I2S_DMA_BUF_LEN   = FRAME_SAMPLES; // samples per DMA buffer

// ~500 ms of 16kHz mono PCM = 8000 samples = 16000 bytes. Lives in PSRAM.
static constexpr size_t PLAYBACK_RING_BYTES = SAMPLE_RATE_HZ * sizeof(int16_t) / 2;

// Firmware version reported in the "hello" frame.
#define FW_VERSION "1.0"
