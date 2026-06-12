"""Ollama LLM adapter (resident, streaming).

Streams tokens from a warm Ollama server. ``keep_alive=-1`` pins the model in
memory so there is never a per-request load. Imported lazily; only needs the
stdlib + httpx-style client at runtime, here using ``aiohttp`` if present and
falling back to a thread-wrapped ``requests`` call.
"""

from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator, List, Tuple

from .base import LLMBackend

SYSTEM_PROMPT = (
    "You are a screenless voice assistant worn as a pendant. Answer in a few "
    "short, spoken-style sentences. Be direct and useful. No markdown, no lists."
)


class OllamaLLM(LLMBackend):
    def __init__(self, url: str = "http://127.0.0.1:11434", model: str = "qwen2.5:3b") -> None:
        self._url = url.rstrip("/")
        self._model = model

    async def prewarm(self) -> None:
        # A tiny generate pins the model in memory (keep_alive=-1).
        try:
            async for _ in self._stream("ready", []):
                break
        except Exception:
            # Prewarm is best-effort; a missing Ollama shouldn't crash startup.
            pass

    def _messages(self, prompt: str, history: List[Tuple[str, str]]):
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
        for user, assistant in history:
            msgs.append({"role": "user", "content": user})
            msgs.append({"role": "assistant", "content": assistant})
        msgs.append({"role": "user", "content": prompt})
        return msgs

    async def generate(self, prompt: str, history: List[Tuple[str, str]]) -> AsyncIterator[str]:
        async for frag in self._stream(prompt, history):
            yield frag

    async def _stream(self, prompt: str, history: List[Tuple[str, str]]) -> AsyncIterator[str]:
        payload = {
            "model": self._model,
            "messages": self._messages(prompt, history),
            "stream": True,
            "keep_alive": -1,
            "options": {"temperature": 0.4},
        }
        try:
            import aiohttp  # type: ignore
        except ImportError:
            aiohttp = None

        if aiohttp is not None:
            async with aiohttp.ClientSession() as sess:
                async with sess.post(f"{self._url}/api/chat", json=payload) as resp:
                    async for line in resp.content:
                        frag = _parse_line(line)
                        if frag:
                            yield frag
            return

        # Fallback: requests streamed in a thread, bridged via a queue.
        import requests  # type: ignore

        queue: "asyncio.Queue[object]" = asyncio.Queue()
        loop = asyncio.get_running_loop()
        _SENTINEL = object()

        def _worker() -> None:
            with requests.post(f"{self._url}/api/chat", json=payload, stream=True) as resp:
                for line in resp.iter_lines():
                    frag = _parse_line(line)
                    if frag:
                        loop.call_soon_threadsafe(queue.put_nowait, frag)
            loop.call_soon_threadsafe(queue.put_nowait, _SENTINEL)

        task = asyncio.create_task(asyncio.to_thread(_worker))
        try:
            while True:
                item = await queue.get()
                if item is _SENTINEL:
                    break
                yield item  # type: ignore[misc]
        finally:
            await task


def _parse_line(line: "bytes | str") -> str:
    if not line:
        return ""
    if isinstance(line, bytes):
        line = line.decode("utf-8", "ignore")
    line = line.strip()
    if not line:
        return ""
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return ""
    return obj.get("message", {}).get("content", "") or ""
