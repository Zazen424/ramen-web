"""Backend factory: maps config strings to backend instances.

Real adapters are imported lazily so the server (and the whole test suite)
runs with zero heavy dependencies when using the mock backends.
"""

from __future__ import annotations

from ..config import Config
from .base import LLMBackend, STTBackend, TTSBackend


def build_stt(cfg: Config) -> STTBackend:
    if cfg.stt_backend == "mock":
        from .mock import MockSTT
        return MockSTT(finalize_s=cfg.mock_stt_finalize_s)
    if cfg.stt_backend == "whisper":
        from .whisper_stt import WhisperSTT
        return WhisperSTT(model=cfg.whisper_model)
    raise ValueError(f"unknown STT backend: {cfg.stt_backend}")


def build_llm(cfg: Config) -> LLMBackend:
    if cfg.llm_backend == "mock":
        from .mock import MockLLM
        return MockLLM(ttft_s=cfg.mock_llm_ttft_s, token_s=cfg.mock_llm_token_s)
    if cfg.llm_backend == "ollama":
        from .ollama_llm import OllamaLLM
        return OllamaLLM(url=cfg.ollama_url, model=cfg.ollama_model)
    raise ValueError(f"unknown LLM backend: {cfg.llm_backend}")


def build_tts(cfg: Config) -> TTSBackend:
    if cfg.tts_backend == "mock":
        from .mock import MockTTS
        return MockTTS(first_chunk_s=cfg.mock_tts_first_s)
    if cfg.tts_backend == "piper":
        from .piper_tts import PiperTTS
        return PiperTTS(voice=cfg.piper_voice)
    raise ValueError(f"unknown TTS backend: {cfg.tts_backend}")
