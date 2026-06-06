"""WebSocket 识别服务端.

每条连接: 先收 START(JSON) 鉴权与声明媒体参数 -> 回 ready ->
持续收二进制 L16 PCM -> 流式 VAD 切片 -> 指纹匹配 -> 回 RESULT(JSON).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time

import numpy as np
import websockets

from . import audio, library as library_admin, states
from .asr import ASRFallback
from .matcher import SampleLibrary
from .vad import StreamingSegmenter

log = logging.getLogger("tonedetect_server")


class RecognitionServer:
    def __init__(self, library: SampleLibrary, key: str | None = None, capture_dir: str | None = None,
                 asr: ASRFallback | None = None, autolearn: bool = False, samples_dir: str | None = None):
        self.library = library
        self.key = key
        self.capture_dir = capture_dir
        self.asr = asr
        self.autolearn = autolearn
        self.samples_dir = samples_dir
        if capture_dir:
            os.makedirs(capture_dir, exist_ok=True)

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
            st = states.by_alias(m.alias)
            if st:
                result["id"] = st.id

        if self.asr is not None:
            if m.tone == "prompt":
                # ASR 兜底:指纹未命中,转写+归类
                asr_res = self.asr.recognize(seg.pcm, self._rate)
                if asr_res is not None:
                    result.update({
                        "tone": "asr",
                        "accuracy": "ACCURACY",
                        "category": asr_res.category,
                        "alias": asr_res.alias,
                        "text": asr_res.text,
                    })
                    st = states.by_alias(asr_res.alias)
                    if st:
                        result["id"] = st.id
                    if self.autolearn and self.samples_dir:
                        self._autolearn(seg, asr_res)
            elif m.tone == "sample" and m.accuracy == "INACCURACY":
                # 交叉校验:指纹候选不够自信时,用 ASR 复核;一致则升为 ACCURACY
                asr_res = self.asr.recognize(seg.pcm, self._rate)
                if asr_res is not None and asr_res.alias == m.alias:
                    result["accuracy"] = "ACCURACY"
                    result["confirmed_by"] = "asr"
                    result["text"] = asr_res.text

        log.info("RESULT %s", result)

        # reflow: persist un-matched (still un-classified) prompts for later labeling
        if self.capture_dir and result["tone"] == "prompt":
            self._capture(seg, m.score)

        await self._safe_send(ws, result)

    def _autolearn(self, seg, asr_res):
        """ASR 归类成功后,自动把该段补进样本库,下次走指纹快路径。"""
        try:
            import time
            name = f"asr_{asr_res.alias.replace(' ', '_')}_{int(time.time() * 1000)}"
            tmp = os.path.join(self.samples_dir, name + ".src.wav")
            os.makedirs(self.samples_dir, exist_ok=True)
            audio.write_wav_mono16(tmp, seg.pcm, self._rate)
            library_admin.add_sample(self.samples_dir, tmp, name=name,
                                     alias=asr_res.alias, category=asr_res.category, rate=self._rate)
            if os.path.isfile(tmp):
                os.remove(tmp)
            self.library.load(self.samples_dir)  # hot-reload so it matches next time
            log.info("autolearn: added sample %s (%s) and reloaded library", name, asr_res.alias)
        except OSError as e:
            log.warning("autolearn failed: %s", e)

    def _capture(self, seg, score: float):
        try:
            base = f"{self._uuid or 'unknown'}_{int(time.time() * 1000)}_{seg.begin_ms}"
            wav = os.path.join(self.capture_dir, base + ".wav")
            audio.write_wav_mono16(wav, seg.pcm, self._rate)
            meta = {
                "uuid": self._uuid,
                "rate": self._rate,
                "begin_ms": seg.begin_ms,
                "end_ms": seg.end_ms,
                "score": round(score, 4),
                "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            with open(os.path.join(self.capture_dir, base + ".json"), "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False)
            log.info("captured un-matched segment -> %s", wav)
        except OSError as e:
            log.warning("capture failed: %s", e)

    @staticmethod
    async def _safe_send(ws, obj: dict):
        try:
            await ws.send(json.dumps(obj, ensure_ascii=False))
        except websockets.ConnectionClosed:
            pass


async def serve(host: str, port: int, library: SampleLibrary,
                key: str | None = None, capture_dir: str | None = None,
                asr: ASRFallback | None = None, autolearn: bool = False, samples_dir: str | None = None):
    server = RecognitionServer(library, key=key, capture_dir=capture_dir,
                               asr=asr, autolearn=autolearn, samples_dir=samples_dir)
    async with websockets.serve(server.handle, host, port, max_size=None):
        log.info("tonedetect recognition server on ws://%s:%d (samples=%d, capture=%s, asr=%s, autolearn=%s)",
                 host, port, len(library.samples), capture_dir or "off",
                 "on" if asr else "off", autolearn)
        await asyncio.Future()  # run forever
