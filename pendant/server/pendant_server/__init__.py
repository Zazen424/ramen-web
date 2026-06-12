"""Screenless AI pendant — Mac mini server.

A warm, streaming, overlapped STT -> LLM -> TTS pipeline behind a WebSocket,
built for low time-to-first-audio. Heavy models sit behind swappable backends
so the orchestration runs and stress tests anywhere with mock backends.
"""

from .config import Config
from .server import PendantServer

__all__ = ["Config", "PendantServer"]
__version__ = "1.0.0"
