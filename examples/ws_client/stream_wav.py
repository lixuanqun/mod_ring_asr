#!/usr/bin/env python3
"""示例:把一个 WAV 经 WebSocket 推给 tonedetect 识别服务,打印返回结果。

模拟 mod_tonedetect 的客户端行为(START -> 二进制 L16 帧 -> 收 RESULT)。
可用于联调任何兼容 docs/INTEGRATION.md 协议的识别服务。

依赖: pip install websockets   (音频读取用标准库 wave)

用法:
  python stream_wav.py --url ws://127.0.0.1:9977/ --wav prompt.wav [--key KEY]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import wave

import websockets


def read_wav_mono16(path: str):
    with wave.open(path, "rb") as w:
        rate, ch, sw, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
        raw = w.readframes(n)
    if sw != 2:
        raise SystemExit("only 16-bit PCM WAV supported")
    if ch > 1:  # take channel 0
        raw = b"".join(raw[i:i + 2] for i in range(0, len(raw), 2 * ch))
    return raw, rate


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="ws://127.0.0.1:9977/")
    ap.add_argument("--wav", required=True)
    ap.add_argument("--key", default="")
    ap.add_argument("--frame-ms", type=int, default=20)
    args = ap.parse_args()

    pcm, rate = read_wav_mono16(args.wav)
    frame = int(rate * args.frame_ms / 1000) * 2  # bytes per frame

    async with websockets.connect(args.url, max_size=None) as ws:
        await ws.send(json.dumps({"type": "start", "version": 1, "uuid": "example",
                                  "codec": "L16", "samplerate": rate, "key": args.key}))
        ready = json.loads(await asyncio.wait_for(ws.recv(), 5))
        print("server:", ready)
        if ready.get("type") != "ready":
            return

        # stream binary L16 frames (pace roughly to real-time)
        for i in range(0, len(pcm), frame):
            await ws.send(pcm[i:i + frame])
            await asyncio.sleep(args.frame_ms / 1000.0)
        await ws.send(json.dumps({"type": "stop"}))

        try:
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), 3))
                if msg.get("type") == "result":
                    print("RESULT:", json.dumps(msg, ensure_ascii=False))
                elif msg.get("type") == "fin":
                    break
        except (asyncio.TimeoutError, websockets.ConnectionClosed):
            pass


if __name__ == "__main__":
    asyncio.run(main())
