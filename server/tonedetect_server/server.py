"""WebSocket 识别服务端.

每条连接: 先收 START(JSON) 鉴权与声明媒体参数 -> 回 ready ->
持续收二进制 L16 PCM -> 流式 VAD 切片 -> 指纹匹配 -> 回 RESULT(JSON).
"""
from __future__ import annotations

import asyncio
import json
import logging

import numpy as np
import websockets

from .matcher import SampleLibrary
from .vad import StreamingSegmenter

log = logging.getLogger("tonedetect_server")


class RecognitionServer:
    def __init__(self, library: SampleLibrary, key: str | None = None):
        self.library = library
        self.key = key

    async def handle(self, ws):
        peer = getattr(ws, "remote_address", None)
        uuid = None
        rate = 8000
        segmenter: StreamingSegmenter | None = None
        try:
            async for message in ws:
                if isinstance(message, str):
                    stop = await self._on_text(ws, message)
                    if stop == "started":
                        # re-read params set on self for this connection
                        rate = self._rate
                        uuid = self._uuid
                        segmenter = StreamingSegmenter(rate=rate)
                    elif stop == "stop":
                        break
                    elif stop == "error":
                        break
                else:
                    if segmenter is None:
                        # ignore audio before START
                        continue
                    pcm = np.frombuffer(message, dtype="<i2")
                    for seg in segmenter.feed(pcm):
                        await self._emit_result(ws, seg)
            # flush trailing segment on close
            if segmenter is not None:
                for seg in segmenter.flush():
                    await self._emit_result(ws, seg)
                await self._safe_send(ws, {"type": "fin"})
        except websockets.ConnectionClosed:
            pass
        finally:
            log.info("connection closed uuid=%s peer=%s", uuid, peer)

    async def _on_text(self, ws, message: str) -> str:
        try:
            msg = json.loads(message)
        except json.JSONDecodeError:
            await self._safe_send(ws, {"type": "error", "reason": "bad_json"})
            return "error"

        mtype = msg.get("type")
        if mtype == "start":
            if self.key and msg.get("key") != self.key:
                await self._safe_send(ws, {"type": "error", "reason": "bad_key"})
                return "error"
            self._uuid = msg.get("uuid")
            self._rate = int(msg.get("samplerate", 8000))
            log.info("START uuid=%s rate=%d codec=%s", self._uuid, self._rate, msg.get("codec"))
            await self._safe_send(ws, {"type": "ready"})
            return "started"
        if mtype == "stop":
            return "stop"
        return "ignore"

    async def _emit_result(self, ws, seg):
        m = self.library.match(seg.pcm, self._rate)
        result = {
            "type": "result",
            "tone": m.tone,
            "accuracy": m.accuracy,
            "score": round(m.score, 4),
            "point_begin": seg.begin_ms,
            "point_end": seg.end_ms,
        }
        if m.tone == "sample":
            result.update({"name": m.name, "alias": m.alias, "category": m.category})
        log.info("RESULT %s", result)
        await self._safe_send(ws, result)

    @staticmethod
    async def _safe_send(ws, obj: dict):
        try:
            await ws.send(json.dumps(obj, ensure_ascii=False))
        except websockets.ConnectionClosed:
            pass


async def serve(host: str, port: int, library: SampleLibrary, key: str | None = None):
    server = RecognitionServer(library, key=key)
    async with websockets.serve(server.handle, host, port, max_size=None):
        log.info("tonedetect recognition server listening on ws://%s:%d (samples=%d)",
                 host, port, len(library.samples))
        await asyncio.Future()  # run forever
