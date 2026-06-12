"""WebSocket server: accept pendant connections, bind each to a Session."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import websockets
from websockets.server import WebSocketServerProtocol

from . import backends
from .config import Config
from .pipeline import Pipeline
from .session import Session

log = logging.getLogger("pendant.server")


class PendantServer:
    def __init__(self, cfg: Optional[Config] = None) -> None:
        self.cfg = cfg or Config()
        self.pipeline = Pipeline(
            backends.build_stt(self.cfg),
            backends.build_llm(self.cfg),
            backends.build_tts(self.cfg),
        )
        self._server: Optional[websockets.server.Serve] = None

    async def prewarm(self) -> None:
        log.info("prewarming backends (stt=%s llm=%s tts=%s)",
                 self.cfg.stt_backend, self.cfg.llm_backend, self.cfg.tts_backend)
        await self.pipeline.prewarm()
        log.info("backends warm")

    async def handler(self, ws: WebSocketServerProtocol) -> None:
        peer = getattr(ws, "remote_address", None)
        log.info("pendant connected: %s", peer)
        session = Session(
            self.pipeline,
            send_text=ws.send,
            send_bytes=ws.send,
            history_turns=self.cfg.history_turns,
            turn_timeout_s=self.cfg.turn_timeout_s,
        )
        try:
            async for message in ws:
                if isinstance(message, (bytes, bytearray)):
                    await session.on_bytes(bytes(message))
                else:
                    await session.on_text(message)
        except websockets.ConnectionClosed:
            log.info("pendant disconnected: %s", peer)

    async def serve_forever(self) -> None:
        await self.prewarm()
        log.info("listening on ws://%s:%s%s", self.cfg.host, self.cfg.port, self.cfg.path)
        async with websockets.serve(
            self.handler, self.cfg.host, self.cfg.port,
            max_size=None,  # audio frames; don't cap message size
            ping_interval=20, ping_timeout=20,
        ):
            await asyncio.Future()  # run until cancelled


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    await PendantServer().serve_forever()
