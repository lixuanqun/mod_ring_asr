#!/usr/bin/env python3
"""示例:自建一个与 mod_tonedetect 兼容的最小识别服务(第三方可照此实现)。

严格按 docs/INTEGRATION.md 的协议契约:
  收 START(文本/JSON) -> 校验 key -> 回 {"type":"ready"}
  收二进制帧(小端 L16 PCM) -> 简单能量 VAD 切段
  每段回一条 {"type":"result", ...}
  收 {"type":"stop"} 或连接关闭 -> 回 {"type":"fin"}

本例的"识别"只做占位(按能量判定 prompt/silence),真实实现把你的
引擎(指纹/ASR/已有系统)接到 classify_segment() 即可。

依赖: pip install websockets   (其余仅标准库)
用法: python minimal_recognition_server.py --host 0.0.0.0 --port 9977 [--key KEY]
"""
from __future__ import annotations

import argparse
import array
import asyncio
import json
import math

import websockets

RMS_THRESHOLD = 300.0
FRAME_MS = 20
HANGOVER_MS = 200
MIN_SEG_MS = 250


def rms(int16_block) -> float:
    if not int16_block:
        return 0.0
    return math.sqrt(sum(s * s for s in int16_block) / len(int16_block))


def classify_segment(pcm, rate) -> dict:
    """占位识别:真实实现替换为指纹/ASR。这里仅按时长返回 prompt。"""
    ms = int(len(pcm) * 1000 / rate)
    # 例如:命中样本时应返回
    #   {"tone":"sample","category":"空号","alias":"does not exist","accuracy":"ACCURACY"}
    return {"tone": "prompt", "accuracy": "LOOSE", "duration_ms": ms}


class Conn:
    def __init__(self, rate):
        self.rate = rate
        self.fsize = max(1, int(rate * FRAME_MS / 1000))
        self.hang = max(1, HANGOVER_MS // FRAME_MS)
        self.min_frames = max(1, MIN_SEG_MS // FRAME_MS)
        self.buf = array.array("h")
        self.in_speech = False
        self.seg = array.array("h")
        self.sil = 0
        self.total_frames = 0
        self.seg_begin = 0

    def feed(self, pcm_bytes):
        out = []
        self.buf.frombytes(pcm_bytes)
        while len(self.buf) >= self.fsize:
            frame = self.buf[:self.fsize]
            del self.buf[:self.fsize]
            cur_ms = self.total_frames * FRAME_MS
            if rms(frame) >= RMS_THRESHOLD:
                if not self.in_speech:
                    self.in_speech, self.seg, self.sil, self.seg_begin = True, array.array("h"), 0, cur_ms
                self.seg.extend(frame)
                self.sil = 0
            elif self.in_speech:
                self.seg.extend(frame)
                self.sil += 1
                if self.sil >= self.hang:
                    if len(self.seg) - self.sil * self.fsize >= self.min_frames * self.fsize:
                        body = self.seg[:len(self.seg) - self.sil * self.fsize]
                        out.append((self.seg_begin, cur_ms, body))
                    self.in_speech = False
            self.total_frames += 1
        return out


async def handler(ws, key):
    rate, conn, started = 8000, None, False
    try:
        async for msg in ws:
            if isinstance(msg, str):
                m = json.loads(msg)
                if m.get("type") == "start":
                    if key and m.get("key") != key:
                        await ws.send(json.dumps({"type": "error", "reason": "bad_key"}))
                        return
                    rate = int(m.get("samplerate", 8000))
                    conn = Conn(rate)
                    started = True
                    await ws.send(json.dumps({"type": "ready"}))
                elif m.get("type") == "stop":
                    break
            elif started and conn is not None:
                for begin, end, body in conn.feed(msg):
                    res = {"type": "result", "point_begin": begin, "point_end": end}
                    res.update(classify_segment(body, rate))
                    await ws.send(json.dumps(res, ensure_ascii=False))
        await ws.send(json.dumps({"type": "fin"}))
    except websockets.ConnectionClosed:
        pass


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=9977)
    ap.add_argument("--key", default="")
    args = ap.parse_args()

    async def h(ws):
        await handler(ws, args.key)

    async with websockets.serve(h, args.host, args.port, max_size=None):
        print(f"minimal recognition server on ws://{args.host}:{args.port}/")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
