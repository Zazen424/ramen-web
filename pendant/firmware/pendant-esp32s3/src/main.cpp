// =============================================================================
// main.cpp — Firmware for a screenless AI voice pendant.
//
//   Seeed XIAO ESP32-S3 Sense + onboard PDM mic + MAX98357A I2S amp.
//
// State machine:
//   DEEP_SLEEP -> (button wakes) -> WIFI_CONNECT -> WS_CONNECT
//              -> STREAMING (button held) -> "end" -> PLAYBACK
//              -> IDLE -> (idle timeout) -> DEEP_SLEEP
//
// Audio in : I2S0 in PDM-RX mode, 16kHz mono PCM16, 40ms (1280B) frames,
//            DMA double-buffered.  Streamed as WS BINARY while the turn is open.
// Audio out: I2S1 to the MAX98357A. Server TTS arrives as WS BINARY between
//            audio_start/audio_end and is fed through a PSRAM ring buffer.
//
// Wire protocol: see config.h / README.md. TEXT = JSON control, BINARY = PCM.
// =============================================================================

#include <Arduino.h>
#include <WiFi.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>
#include <driver/i2s.h>
#include <driver/rtc_io.h>
#include <esp_sleep.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <freertos/ringbuf.h>

#include "config.h"

// I2S peripheral assignments.
static constexpr i2s_port_t I2S_MIC = I2S_NUM_0;  // PDM RX  (microphone)
static constexpr i2s_port_t I2S_AMP = I2S_NUM_1;  // std TX  (speaker amp)

// =============================================================================
// Application state
// =============================================================================
enum class AppState {
  BOOT,
  WIFI_CONNECT,
  WS_CONNECT,
  IDLE,        // session warm, mic not streaming
  STREAMING,   // button held, sending mic frames
  PLAYBACK,    // receiving + playing TTS
  ERROR,
};

static AppState  g_state          = AppState::BOOT;
static uint32_t  g_turn           = 0;       // monotonically increasing turn id
static uint32_t  g_lastActivityMs = 0;       // for idle timeout
static bool      g_wsConnected    = false;
static bool      g_serverReady    = false;   // got {"t":"ready"}
static bool      g_audioPlaying    = false;  // between audio_start and audio_end

// Reconnect backoff state.
static uint32_t  g_backoffMs       = WS_BACKOFF_MIN_MS;
static uint32_t  g_nextReconnectMs = 0;

static WebSocketsClient g_ws;

// Playback ring buffer (PSRAM-backed, filled by WS callback, drained by amp task).
static RingbufHandle_t g_playRing = nullptr;

// =============================================================================
// LED — single channel, active-low onboard user LED.
//   off          = idle / sleep
//   solid        = capturing (we use a gentle breathing effect)
//   slow blink   = connecting
//   double blink = error
// =============================================================================
namespace led {

enum class Pattern { OFF, BREATHE, SLOW_BLINK, DOUBLE_BLINK };
static Pattern   s_pattern = Pattern::OFF;
static uint32_t  s_phaseStartMs = 0;

inline void write(bool on) {
  // Active-low: LOW = on.
  digitalWrite(PIN_LED, (on ^ LED_ACTIVE_LOW) ? HIGH : LOW);
}

// PWM-free "breathing" by toggling with a duty derived from a triangle wave.
inline void breatheStep(uint32_t t) {
  const uint32_t period = 2000;                 // 2s breath
  uint32_t ph = t % period;
  uint32_t tri = ph < period / 2 ? ph : period - ph;     // 0..1000..0
  uint8_t duty = (uint8_t)((tri * 255) / (period / 2));  // 0..255
  // Software PWM at ~1kHz using micros within this call window is overkill;
  // approximate by comparing against a fast sub-millisecond counter.
  write((micros() / 4 % 256) < duty);
}

void init() {
  pinMode(PIN_LED, OUTPUT);
  write(false);
}

void set(Pattern p) {
  if (p != s_pattern) { s_pattern = p; s_phaseStartMs = millis(); }
}

// Call frequently from the main loop.
void update() {
  uint32_t now = millis();
  uint32_t t   = now - s_phaseStartMs;
  switch (s_pattern) {
    case Pattern::OFF:
      write(false);
      break;
    case Pattern::BREATHE:
      breatheStep(t);
      break;
    case Pattern::SLOW_BLINK:
      write((t % 1000) < 500);            // 0.5s on / 0.5s off
      break;
    case Pattern::DOUBLE_BLINK: {
      uint32_t ph = t % 1200;             // two quick blinks then pause
      bool on = (ph < 120) || (ph >= 240 && ph < 360);
      write(on);
      break;
    }
  }
}

} // namespace led

// =============================================================================
// Button — momentary, active-low (pressed = LOW), debounced.
// =============================================================================
namespace button {

static bool     s_pressed     = false;   // debounced logical state
static bool     s_lastRaw     = true;    // raw reading (HIGH = released)
static uint32_t s_lastEdgeMs  = 0;

static bool s_edgeDown = false;          // consumed by main loop
static bool s_edgeUp   = false;

void init() {
  pinMode(PIN_BUTTON, INPUT_PULLUP);
  s_lastRaw = digitalRead(PIN_BUTTON);
  s_pressed = !s_lastRaw;
}

// Poll + debounce. Sets edge flags for the main loop to consume.
void update() {
  bool raw = digitalRead(PIN_BUTTON);      // HIGH = released, LOW = pressed
  uint32_t now = millis();
  if (raw != s_lastRaw) {
    s_lastRaw = raw;
    s_lastEdgeMs = now;
  }
  if ((now - s_lastEdgeMs) >= BUTTON_DEBOUNCE_MS) {
    bool pressedNow = !raw;
    if (pressedNow != s_pressed) {
      s_pressed = pressedNow;
      if (pressedNow) s_edgeDown = true;
      else            s_edgeUp   = true;
    }
  }
}

bool isPressed()        { return s_pressed; }
bool takeDownEdge()     { bool e = s_edgeDown; s_edgeDown = false; return e; }
bool takeUpEdge()       { bool e = s_edgeUp;   s_edgeUp   = false; return e; }

} // namespace button

// =============================================================================
// Audio IN — I2S0 PDM-RX from the onboard microphone.
// =============================================================================
namespace audio_in {

static bool s_running = false;

void init() {
  i2s_config_t cfg = {};
  cfg.mode                 = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX | I2S_MODE_PDM);
  cfg.sample_rate          = SAMPLE_RATE_HZ;
  cfg.bits_per_sample      = I2S_BITS_PER_SAMPLE_16BIT;
  cfg.channel_format       = I2S_CHANNEL_FMT_ONLY_LEFT;   // mono
  cfg.communication_format = I2S_COMM_FORMAT_STAND_I2S;
  cfg.intr_alloc_flags     = ESP_INTR_FLAG_LEVEL1;
  cfg.dma_buf_count        = I2S_DMA_BUF_COUNT;
  cfg.dma_buf_len          = I2S_DMA_BUF_LEN;             // samples per DMA buffer
  cfg.use_apll             = false;
  cfg.tx_desc_auto_clear   = false;

  ESP_ERROR_CHECK(i2s_driver_install(I2S_MIC, &cfg, 0, nullptr));

  // For PDM RX only CLK + DIN are used; WS/SCK fields are unused.
  i2s_pin_config_t pins = {};
  pins.mck_io_num   = I2S_PIN_NO_CHANGE;
  pins.bck_io_num   = I2S_PIN_NO_CHANGE;
  pins.ws_io_num    = PIN_PDM_CLK;     // PDM clock
  pins.data_out_num = I2S_PIN_NO_CHANGE;
  pins.data_in_num  = PIN_PDM_DATA;    // PDM data
  ESP_ERROR_CHECK(i2s_set_pin(I2S_MIC, &pins));

  i2s_stop(I2S_MIC);  // don't run the mic until a turn starts
}

void start() {
  if (s_running) return;
  i2s_zero_dma_buffer(I2S_MIC);
  i2s_start(I2S_MIC);
  s_running = true;
}

void stop() {
  if (!s_running) return;
  i2s_stop(I2S_MIC);
  s_running = false;
}

// Read exactly one frame (blocking up to `to_ms`). Returns bytes read.
// `out` must hold FRAME_BYTES. No per-sample copy — i2s_read fills the buffer.
size_t readFrame(uint8_t* out, uint32_t to_ms) {
  size_t got = 0;
  esp_err_t err = i2s_read(I2S_MIC, out, FRAME_BYTES, &got, pdMS_TO_TICKS(to_ms));
  if (err != ESP_OK) return 0;
  return got;
}

} // namespace audio_in

// =============================================================================
// Audio OUT — I2S1 standard TX to the MAX98357A.
// A dedicated FreeRTOS task drains the PSRAM ring buffer into I2S so playback
// keeps flowing while the main loop services the network and button.
// =============================================================================
namespace audio_out {

static TaskHandle_t s_task = nullptr;

void init() {
  i2s_config_t cfg = {};
  cfg.mode                 = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX);
  cfg.sample_rate          = SAMPLE_RATE_HZ;
  cfg.bits_per_sample      = I2S_BITS_PER_SAMPLE_16BIT;
  cfg.channel_format       = I2S_CHANNEL_FMT_ONLY_LEFT;   // mono -> mono amp
  cfg.communication_format = I2S_COMM_FORMAT_STAND_I2S;
  cfg.intr_alloc_flags     = ESP_INTR_FLAG_LEVEL1;
  cfg.dma_buf_count        = I2S_DMA_BUF_COUNT;
  cfg.dma_buf_len          = I2S_DMA_BUF_LEN;
  cfg.use_apll             = false;
  cfg.tx_desc_auto_clear   = true;                        // emit silence on underrun

  ESP_ERROR_CHECK(i2s_driver_install(I2S_AMP, &cfg, 0, nullptr));

  i2s_pin_config_t pins = {};
  pins.mck_io_num   = I2S_PIN_NO_CHANGE;
  pins.bck_io_num   = PIN_AMP_BCLK;
  pins.ws_io_num    = PIN_AMP_LRCLK;
  pins.data_out_num = PIN_AMP_DIN;
  pins.data_in_num  = I2S_PIN_NO_CHANGE;
  ESP_ERROR_CHECK(i2s_set_pin(I2S_AMP, &pins));

  i2s_stop(I2S_AMP);
}

// Push received PCM bytes into the ring buffer (called from WS callback).
// Drops the frame on overflow rather than blocking the network.
void enqueue(const uint8_t* data, size_t len) {
  if (!g_playRing) return;
  // Non-blocking send; if full, skip (prevents WS callback stalls).
  xRingbufferSend(g_playRing, data, len, 0);
}

// Discard any queued audio (used on barge-in / cancel).
void flush() {
  if (!g_playRing) return;
  size_t sz;
  void* item;
  while ((item = xRingbufferReceive(g_playRing, &sz, 0)) != nullptr) {
    vRingbufferReturnItem(g_playRing, item);
  }
  i2s_zero_dma_buffer(I2S_AMP);
}

// Amp task: pull from ring, write to I2S. Runs forever.
static void task(void*) {
  uint8_t scratch[FRAME_BYTES];
  for (;;) {
    size_t sz = 0;
    // Wait briefly for data; xRingbufferReceiveUpTo gives us contiguous bytes.
    void* item = xRingbufferReceiveUpTo(g_playRing, &sz, pdMS_TO_TICKS(20), sizeof(scratch));
    if (item && sz) {
      size_t written = 0;
      i2s_write(I2S_AMP, item, sz, &written, portMAX_DELAY);
      vRingbufferReturnItem(g_playRing, item);
    }
    // When idle the I2S driver auto-clears to silence (tx_desc_auto_clear).
  }
}

void begin() {
  i2s_zero_dma_buffer(I2S_AMP);
  i2s_start(I2S_AMP);
}

void end() {
  i2s_stop(I2S_AMP);
}

void startTask() {
  if (s_task) return;
  // Ring buffer in PSRAM-friendly byte mode.
  g_playRing = xRingbufferCreate(PLAYBACK_RING_BYTES, RINGBUF_TYPE_BYTEBUF);
  configASSERT(g_playRing);
  xTaskCreatePinnedToCore(task, "amp", 4096, nullptr, 5, &s_task, 1);
}

} // namespace audio_out

// =============================================================================
// WebSocket control + transport
// =============================================================================
namespace ws {

// --- Outgoing TEXT helpers ---
static void sendJson(const JsonDocument& doc) {
  String s;
  serializeJson(doc, s);
  g_ws.sendTXT(s);
}

void sendHello() {
  JsonDocument d;
  d["t"]   = "hello";
  d["fw"]  = FW_VERSION;
  d["sr"]  = (int)SAMPLE_RATE_HZ;
  d["fmt"] = "pcm16";
  sendJson(d);
}

void sendStart(uint32_t turn) {
  JsonDocument d; d["t"] = "start"; d["turn"] = turn; sendJson(d);
}
void sendEnd(uint32_t turn) {
  JsonDocument d; d["t"] = "end"; d["turn"] = turn; sendJson(d);
}
void sendCancel(uint32_t turn) {
  JsonDocument d; d["t"] = "cancel"; d["turn"] = turn; sendJson(d);
}
void sendPing() {
  JsonDocument d; d["t"] = "ping"; d["ts"] = (uint32_t)millis(); sendJson(d);
}

// Send a 1280-byte mic frame as a BINARY message.
void sendMicFrame(const uint8_t* data, size_t len) {
  g_ws.sendBIN(data, len);
}

// --- Incoming TEXT control handler ---
static void handleText(uint8_t* payload, size_t len) {
  JsonDocument d;
  if (deserializeJson(d, payload, len)) {
    Serial.println("[ws] bad JSON");
    return;
  }
  const char* t = d["t"] | "";
  g_lastActivityMs = millis();

  if (!strcmp(t, "ready")) {
    g_serverReady = true;
    Serial.println("[ws] server ready");
  } else if (!strcmp(t, "partial")) {
    Serial.printf("[asr] partial: %s\n", (const char*)(d["text"] | ""));
  } else if (!strcmp(t, "final")) {
    Serial.printf("[asr] final: %s\n", (const char*)(d["text"] | ""));
  } else if (!strcmp(t, "say")) {
    Serial.printf("[tts] say: %s\n", (const char*)(d["text"] | ""));
  } else if (!strcmp(t, "audio_start")) {
    g_audioPlaying = true;
    audio_out::flush();          // start clean
    audio_out::begin();
    g_state = AppState::PLAYBACK;
    Serial.println("[tts] audio_start");
  } else if (!strcmp(t, "audio_end")) {
    g_audioPlaying = false;
    Serial.println("[tts] audio_end");
    // PLAYBACK->IDLE transition handled in main loop once ring drains.
  } else if (!strcmp(t, "done")) {
    Serial.println("[ws] turn done");
  } else if (!strcmp(t, "pong")) {
    // keepalive ack
  } else if (!strcmp(t, "error")) {
    Serial.printf("[ws] server error: %s\n", (const char*)(d["msg"] | ""));
  }
}

// --- WebSocket event callback ---
static void onEvent(WStype_t type, uint8_t* payload, size_t len) {
  switch (type) {
    case WStype_CONNECTED:
      Serial.println("[ws] connected");
      g_wsConnected = true;
      g_serverReady = false;
      g_backoffMs   = WS_BACKOFF_MIN_MS;   // reset backoff on success
      sendHello();
      break;

    case WStype_DISCONNECTED:
      Serial.println("[ws] disconnected");
      g_wsConnected = false;
      g_serverReady = false;
      break;

    case WStype_TEXT:
      handleText(payload, len);
      break;

    case WStype_BIN:
      // TTS PCM. Only meaningful between audio_start/audio_end, but enqueue
      // unconditionally — the ring is flushed on audio_start so stray frames
      // outside a playback window are harmless.
      if (g_audioPlaying) {
        audio_out::enqueue(payload, len);
        g_lastActivityMs = millis();
      }
      break;

    case WStype_ERROR:
      Serial.println("[ws] error");
      break;

    default:
      break;
  }
}

void init() {
  // Register the callback / options once. The actual connection is kicked
  // off by ensureConnected() (which also drives backoff).
  g_ws.onEvent(onEvent);
  // We manage reconnection/backoff ourselves; disable the lib's auto-retry
  // so the two don't fight. (0 = off.)
  g_ws.setReconnectInterval(0);
  // Library-level heartbeat (ping/pong) keeps NAT + socket alive.
  g_ws.enableHeartbeat(WS_PING_INTERVAL_MS, WS_PING_INTERVAL_MS / 2, 2);
  g_nextReconnectMs = 0;   // allow an immediate first attempt
}

// Pump the socket; call every loop iteration.
void loop() { g_ws.loop(); }

bool connected() { return g_wsConnected; }

// Kick a (re)connection attempt with backoff.
void ensureConnected() {
  if (g_wsConnected) return;
  uint32_t now = millis();
  if (now < g_nextReconnectMs) return;
  Serial.printf("[ws] connecting to ws://%s:%d%s\n", SERVER_HOST, SERVER_PORT, SERVER_PATH);
  g_ws.disconnect();
  g_ws.begin(SERVER_HOST, SERVER_PORT, SERVER_PATH);
  // Schedule next attempt and grow backoff.
  g_nextReconnectMs = now + g_backoffMs;
  g_backoffMs = min<uint32_t>(g_backoffMs * 2, WS_BACKOFF_MAX_MS);
}

} // namespace ws

// =============================================================================
// Wi-Fi
// =============================================================================
namespace wifi {

void init() {
  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);   // low latency for streaming
}

// Blocking connect with timeout. Returns true on success.
bool connect() {
  Serial.printf("[wifi] connecting to %s ...\n", WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED) {
    if (millis() - start > WIFI_CONNECT_TIMEOUT_MS) {
      Serial.println("[wifi] connect timeout");
      return false;
    }
    led::update();          // keep the slow-blink animating
    delay(50);
  }
  Serial.printf("[wifi] connected, ip=%s\n", WiFi.localIP().toString().c_str());
  return true;
}

bool connected() { return WiFi.status() == WL_CONNECTED; }

} // namespace wifi

// =============================================================================
// Deep sleep
// =============================================================================
namespace sleep {

// Configure ext0 wake on the button pin (active-low -> wake on LOW level).
void enterDeepSleep() {
  Serial.println("[sleep] entering deep sleep");
  Serial.flush();

  led::set(led::Pattern::OFF);
  led::update();

  // Stop peripherals cleanly.
  audio_in::stop();
  audio_out::end();
  g_ws.disconnect();
  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);

  // Wake when the button is pressed (pulled to GND = LOW).
  esp_sleep_enable_ext0_wakeup(PIN_BUTTON, 0 /* wake on LOW */);
  // Keep the internal pull-up alive during sleep so the line stays HIGH idle.
  rtc_gpio_pullup_en(PIN_BUTTON);
  rtc_gpio_pulldown_dis(PIN_BUTTON);

  esp_deep_sleep_start();   // never returns; chip resets on wake
}

} // namespace sleep

// =============================================================================
// Turn control — start / end / barge-in
// =============================================================================
static void beginTurn() {
  g_turn++;
  Serial.printf("[turn] start #%u\n", g_turn);
  ws::sendStart(g_turn);
  audio_in::start();
  g_state = AppState::STREAMING;
  led::set(led::Pattern::BREATHE);
  g_lastActivityMs = millis();
}

static void endTurn() {
  Serial.printf("[turn] end #%u\n", g_turn);
  audio_in::stop();
  ws::sendEnd(g_turn);
  g_state = AppState::IDLE;           // wait for server audio
  led::set(led::Pattern::OFF);
  g_lastActivityMs = millis();
}

// Barge-in: cancel whatever is playing and immediately start a fresh turn.
static void bargeIn() {
  Serial.println("[turn] barge-in");
  ws::sendCancel(g_turn);
  g_audioPlaying = false;
  audio_out::flush();
  audio_out::end();
  beginTurn();
}

// Stream one mic frame if one is ready.
static void pumpMicStreaming() {
  static uint8_t frame[FRAME_BYTES];
  size_t got = audio_in::readFrame(frame, /*to_ms=*/FRAME_MS + 10);
  if (got == FRAME_BYTES && ws::connected()) {
    ws::sendMicFrame(frame, got);
    g_lastActivityMs = millis();
  }
}

// =============================================================================
// Arduino entry points
// =============================================================================
void setup() {
  Serial.begin(115200);
  delay(50);
  Serial.println("\n[boot] AI voice pendant fw " FW_VERSION);

  // Why did we wake? (Informational.)
  esp_sleep_wakeup_cause_t cause = esp_sleep_get_wakeup_cause();
  Serial.printf("[boot] wake cause: %d\n", (int)cause);

  led::init();
  button::init();
  audio_in::init();
  audio_out::init();
  audio_out::startTask();   // amp drain task + ring buffer
  wifi::init();

  led::set(led::Pattern::SLOW_BLINK);
  g_state = AppState::WIFI_CONNECT;
  g_lastActivityMs = millis();
}

void loop() {
  // Always-serviced subsystems.
  button::update();
  led::update();

  switch (g_state) {

    // -------------------------------------------------------------------------
    case AppState::WIFI_CONNECT: {
      led::set(led::Pattern::SLOW_BLINK);
      if (wifi::connect()) {
        ws::init();
        g_state = AppState::WS_CONNECT;
      } else {
        led::set(led::Pattern::DOUBLE_BLINK);
        delay(500);                 // brief error indication, then retry
      }
      break;
    }

    // -------------------------------------------------------------------------
    case AppState::WS_CONNECT: {
      led::set(led::Pattern::SLOW_BLINK);
      ws::ensureConnected();
      ws::loop();
      if (ws::connected()) {
        g_state = AppState::IDLE;
        led::set(led::Pattern::OFF);
        g_lastActivityMs = millis();
        Serial.println("[state] -> IDLE");
      }
      // If Wi-Fi dropped while connecting WS, go back and re-acquire it.
      if (!wifi::connected()) g_state = AppState::WIFI_CONNECT;
      break;
    }

    // -------------------------------------------------------------------------
    case AppState::IDLE: {
      ws::loop();

      // Lost the link? Reconnect.
      if (!wifi::connected())      { g_state = AppState::WIFI_CONNECT; break; }
      if (!ws::connected())        { g_state = AppState::WS_CONNECT;   break; }

      // App-level keepalive ping.
      static uint32_t lastPing = 0;
      if (millis() - lastPing > WS_PING_INTERVAL_MS) {
        lastPing = millis();
        ws::sendPing();
      }

      // Button down -> start a turn.
      if (button::takeDownEdge()) {
        beginTurn();
        break;
      }
      button::takeUpEdge();   // discard any stale up edge

      // Idle timeout -> deep sleep.
      if (millis() - g_lastActivityMs > IDLE_TIMEOUT_MS) {
        sleep::enterDeepSleep();   // does not return
      }
      break;
    }

    // -------------------------------------------------------------------------
    case AppState::STREAMING: {
      ws::loop();

      if (!ws::connected()) {
        // Link died mid-turn: abort cleanly back to reconnect.
        audio_in::stop();
        g_state = AppState::WS_CONNECT;
        break;
      }

      // Stream mic frames while the button is held.
      pumpMicStreaming();

      // Button released -> endpoint the turn.
      if (button::takeUpEdge() || !button::isPressed()) {
        endTurn();
      }
      break;
    }

    // -------------------------------------------------------------------------
    case AppState::PLAYBACK: {
      ws::loop();

      // Barge-in: a fresh press during playback cancels + restarts.
      if (button::takeDownEdge()) {
        bargeIn();
        break;
      }

      // Playback finishes when the server signaled audio_end AND the ring has
      // drained (we approximate "drained" by no pending bytes).
      if (!g_audioPlaying) {
        size_t freeBytes = g_playRing ? xRingbufferGetCurFreeSize(g_playRing) : 0;
        bool drained = (freeBytes >= PLAYBACK_RING_BYTES - FRAME_BYTES);
        if (drained) {
          audio_out::end();
          g_state = AppState::IDLE;
          led::set(led::Pattern::OFF);
          g_lastActivityMs = millis();
          Serial.println("[state] PLAYBACK -> IDLE");
        }
      }

      if (!ws::connected()) g_state = AppState::WS_CONNECT;
      break;
    }

    // -------------------------------------------------------------------------
    case AppState::ERROR:
    default:
      led::set(led::Pattern::DOUBLE_BLINK);
      delay(200);
      g_state = AppState::WIFI_CONNECT;   // attempt recovery
      break;
  }
}
