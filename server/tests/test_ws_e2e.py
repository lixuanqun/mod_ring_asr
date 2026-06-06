"""端到端: 启动 WebSocket 服务 -> 客户端 START + 流式推 L16 -> 收 RESULT.

完整验证 阶段2 协议链路 (与真实 mod 走同一套 START/AUDIO/RESULT).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile

import numpy as np
import websockets

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tonedetect_server import audio                         # noqa: E402
from tonedetect_server.matcher import SampleLibrary         # noqa: E402
from tonedetect_server.server import RecognitionServer      # noqa: E402
import synth                                                # noqa: E402

RATE = 8000
PORT = 18977


def build_library(tmp: str) -> SampleLibrary:
    clip_a = synth.announcement(seed=1)
    audio.write_wav_mono16(os.path.join(tmp, "konghao.wav"), clip_a, RATE)
    with open(os.path.join(tmp, "samples.json"), "w", encoding="utf-8") as f:
        json.dump([{"file": "konghao.wav", "name": "konghao_yidong",
                    "alias": "does not exist", "category": "空号"}], f, ensure_ascii=False)
    return SampleLibrary(samples_dir=tmp)


async def stream_and_collect(uri: str, pcm: np.ndarray) -> list[dict]:
    results: list[dict] = []
    async with websockets.connect(uri, max_size=None) as ws:
        await ws.send(json.dumps({"type": "start", "version": 1, "uuid": "test-uuid",
                                  "codec": "L16", "samplerate": RATE, "key": None}))
        ready = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert ready.get("type") == "ready", f"expected ready, got {ready}"

        chunk = int(RATE * 0.02)  # 20ms binary frames
        for i in range(0, pcm.size, chunk):
            await ws.send(pcm[i:i + chunk].astype("<i2").tobytes())
        await ws.send(json.dumps({"type": "stop"}))

        try:
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))
                if msg.get("type") == "result":
                    results.append(msg)
                elif msg.get("type") == "fin":
                    break
        except (asyncio.TimeoutError, websockets.ConnectionClosed):
            pass
    return results


async def main() -> int:
    rc = 0
    with tempfile.TemporaryDirectory() as tmp:
        library = build_library(tmp)
        server = RecognitionServer(library, key=None)
        async with websockets.serve(server.handle, "127.0.0.1", PORT, max_size=None):
            uri = f"ws://127.0.0.1:{PORT}/"

            # 1) degraded copy of the registered sample -> should MATCH
            a = synth.announcement(seed=1)
            stream_a = synth.with_silence(synth.degrade(a, gain=0.5, noise=150),
                                          lead_ms=300, tail_ms=500)
            print("== stream degraded sample (expect match: 空号) ==")
            res_a = await stream_and_collect(uri, stream_a)
            for r in res_a:
                print(f"  RESULT {r}")
            matched = [r for r in res_a if r.get("tone") == "sample"
                       and r.get("alias") == "does not exist" and r.get("accuracy") == "ACCURACY"]
            if matched:
                print("  PASS (matched 空号 with ACCURACY)")
            else:
                print("  FAIL (did not match registered sample)")
                rc = 1

            # 2) a different clip -> should NOT match the sample
            b = synth.announcement(seed=2)
            stream_b = synth.with_silence(b, lead_ms=300, tail_ms=500)
            print("== stream different clip (expect NO sample match) ==")
            res_b = await stream_and_collect(uri, stream_b)
            for r in res_b:
                print(f"  RESULT {r}")
            bad = [r for r in res_b if r.get("tone") == "sample" and r.get("alias") == "does not exist"]
            if not bad:
                print("  PASS (different clip not mis-matched)")
            else:
                print("  FAIL (different clip wrongly matched as 空号)")
                rc = 1

    print("ALL PASSED" if rc == 0 else "SOME FAILED")
    return rc


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
