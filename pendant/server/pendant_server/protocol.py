"""Wire protocol for the pendant <-> Mac mini server link.

Transport is a single WebSocket. We use the two native WebSocket frame
types to cheaply separate control from audio:

    * TEXT frames   -> JSON control messages (this module)
    * BINARY frames -> raw little-endian PCM16 mono @ 16 kHz audio

Audio direction is implied by context: uplink binary between ``start`` and
``end`` is microphone audio; downlink binary between ``audio_start`` and
``audio_end`` is synthesized speech. Keeping audio as raw PCM means zero
encode cost on the MCU and zero decode cost in Whisper/Piper -- see the
design doc's "no needless conversion" rule.

All control messages carry a short ``t`` (type) field. Helper builders below
keep both the firmware and the server honest about the exact shape.
"""

from __future__ import annotations

import json
from typing import Any, Dict

# Audio format constants -- the single source of truth shared by every stage.
SAMPLE_RATE = 16_000
CHANNELS = 1
SAMPLE_WIDTH = 2  # bytes, PCM16
FRAME_MS = 40
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000          # 640 samples
FRAME_BYTES = FRAME_SAMPLES * SAMPLE_WIDTH * CHANNELS    # 1280 bytes

# ---- Message type tags -------------------------------------------------------

# pendant -> server
HELLO = "hello"
START = "start"
END = "end"
CANCEL = "cancel"
PING = "ping"

# server -> pendant
READY = "ready"
PARTIAL = "partial"
FINAL = "final"
SAY = "say"
AUDIO_START = "audio_start"
AUDIO_END = "audio_end"
DONE = "done"
PONG = "pong"
ERROR = "error"


def encode(msg: Dict[str, Any]) -> str:
    """Serialize a control message to a compact JSON TEXT frame."""
    return json.dumps(msg, separators=(",", ":"))


def decode(text: str) -> Dict[str, Any]:
    """Parse a control TEXT frame. Raises ``ValueError`` on malformed input."""
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise ValueError(f"invalid control frame: {exc}") from exc
    if not isinstance(obj, dict) or "t" not in obj:
        raise ValueError("control frame missing 't' field")
    return obj


# ---- pendant -> server builders ---------------------------------------------

def hello(fw: str = "1.0", sr: int = SAMPLE_RATE, fmt: str = "pcm16") -> Dict[str, Any]:
    return {"t": HELLO, "fw": fw, "sr": sr, "fmt": fmt}


def start(turn: int) -> Dict[str, Any]:
    return {"t": START, "turn": turn}


def end(turn: int) -> Dict[str, Any]:
    return {"t": END, "turn": turn}


def cancel(turn: int) -> Dict[str, Any]:
    return {"t": CANCEL, "turn": turn}


def ping(ts_ms: int) -> Dict[str, Any]:
    return {"t": PING, "ts": ts_ms}


# ---- server -> pendant builders ---------------------------------------------

def ready() -> Dict[str, Any]:
    return {"t": READY}


def partial(turn: int, text: str) -> Dict[str, Any]:
    return {"t": PARTIAL, "turn": turn, "text": text}


def final(turn: int, text: str) -> Dict[str, Any]:
    return {"t": FINAL, "turn": turn, "text": text}


def say(turn: int, text: str) -> Dict[str, Any]:
    return {"t": SAY, "turn": turn, "text": text}


def audio_start(turn: int, sr: int = SAMPLE_RATE) -> Dict[str, Any]:
    return {"t": AUDIO_START, "turn": turn, "sr": sr}


def audio_end(turn: int) -> Dict[str, Any]:
    return {"t": AUDIO_END, "turn": turn}


def done(turn: int, metrics: Dict[str, Any]) -> Dict[str, Any]:
    return {"t": DONE, "turn": turn, "metrics": metrics}


def pong(ts_ms: int) -> Dict[str, Any]:
    return {"t": PONG, "ts": ts_ms}


def error(msg: str) -> Dict[str, Any]:
    return {"t": ERROR, "msg": msg}
