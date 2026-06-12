"""Server configuration.

Defaults target the *fast path* from the design doc (mock backends so the
pipeline runs anywhere). On the real Mac mini you flip ``stt_backend`` /
``llm_backend`` / ``tts_backend`` to the resident-model adapters via env vars
-- no code change, matching the doc's "swap pieces without changing the
architecture" rule.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from typing import Any, Dict


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


@dataclass
class Config:
    host: str = field(default_factory=lambda: _env("PENDANT_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: _env_int("PENDANT_PORT", 8765))
    path: str = field(default_factory=lambda: _env("PENDANT_WS_PATH", "/pendant"))

    # Backend selection: "mock" | "whisper" | "ollama" | "piper".
    stt_backend: str = field(default_factory=lambda: _env("PENDANT_STT", "mock"))
    llm_backend: str = field(default_factory=lambda: _env("PENDANT_LLM", "mock"))
    tts_backend: str = field(default_factory=lambda: _env("PENDANT_TTS", "mock"))

    # Real-backend addressing (ignored by mocks).
    ollama_url: str = field(default_factory=lambda: _env("OLLAMA_URL", "http://127.0.0.1:11434"))
    ollama_model: str = field(default_factory=lambda: _env("OLLAMA_MODEL", "qwen2.5:3b"))
    whisper_model: str = field(default_factory=lambda: _env("WHISPER_MODEL", "distil-small.en"))
    piper_voice: str = field(default_factory=lambda: _env("PIPER_VOICE", "en_US-amy-medium"))

    # Conversation memory: how many prior (user, assistant) turns to keep.
    history_turns: int = field(default_factory=lambda: _env_int("PENDANT_HISTORY", 6))

    # Per-turn safety timeout (seconds). A turn that exceeds this is aborted.
    turn_timeout_s: float = field(default_factory=lambda: _env_float("PENDANT_TURN_TIMEOUT", 20.0))

    # Mock backend simulated compute (seconds). Lets stress tests exercise a
    # realistic warm-pipeline latency without the real models installed.
    mock_stt_finalize_s: float = field(default_factory=lambda: _env_float("MOCK_STT_FINALIZE", 0.10))
    mock_llm_ttft_s: float = field(default_factory=lambda: _env_float("MOCK_LLM_TTFT", 0.12))
    mock_llm_token_s: float = field(default_factory=lambda: _env_float("MOCK_LLM_TOKEN", 0.010))
    mock_tts_first_s: float = field(default_factory=lambda: _env_float("MOCK_TTS_FIRST", 0.05))

    def summary(self) -> Dict[str, Any]:
        return asdict(self)
