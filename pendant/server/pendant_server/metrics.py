"""Per-turn latency accounting.

The headline number is TTFA (time-to-first-audio): from receipt of the
``end`` control (button release == endpoint) to the first downlink audio
chunk. Everything else is here to explain a TTFA regression.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


def _now() -> float:
    return time.perf_counter()


@dataclass
class TurnMetrics:
    """Timestamps (perf_counter seconds) captured across one turn."""

    t_start: float = field(default_factory=_now)        # button down / turn open
    t_end: Optional[float] = None                       # button up / endpoint
    t_asr_final: Optional[float] = None                 # final transcript ready
    t_llm_first: Optional[float] = None                 # first LLM token
    t_first_audio: Optional[float] = None               # first downlink audio chunk
    t_done: Optional[float] = None                      # turn complete
    audio_bytes: int = 0
    cancelled: bool = False

    def mark_end(self) -> None:
        self.t_end = _now()

    def mark_asr_final(self) -> None:
        self.t_asr_final = _now()

    def mark_llm_first(self) -> None:
        if self.t_llm_first is None:
            self.t_llm_first = _now()

    def mark_first_audio(self) -> None:
        if self.t_first_audio is None:
            self.t_first_audio = _now()

    def mark_done(self) -> None:
        self.t_done = _now()

    @staticmethod
    def _ms(a: Optional[float], b: Optional[float]) -> Optional[float]:
        if a is None or b is None:
            return None
        return round((b - a) * 1000.0, 1)

    def ttfa_ms(self) -> Optional[float]:
        """The metric that matters: endpoint -> first audio."""
        return self._ms(self.t_end, self.t_first_audio)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "asr_final_ms": self._ms(self.t_end, self.t_asr_final),
            "llm_ttft_ms": self._ms(self.t_asr_final, self.t_llm_first),
            "ttfa_ms": self.ttfa_ms(),
            "total_ms": self._ms(self.t_end, self.t_done),
            "audio_bytes": self.audio_bytes,
            "cancelled": self.cancelled,
        }
