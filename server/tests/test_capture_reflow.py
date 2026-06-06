"""端到端闭环: 未命中回流 -> 打标入库 -> 重载 -> 命中.

1. 空样本库 + 开启 capture-dir, 流式推一段提示音 -> 返回 prompt 且落盘到 capture
2. 用 library.promote 把该录音标为 "空号" 入库
3. 重新加载样本库, 再推该提示音(劣化版) -> 命中 sample/空号/ACCURACY
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

from tonedetect_server import library                        # noqa: E402
from tonedetect_server.matcher import SampleLibrary          # noqa: E402
from tonedetect_server.server import RecognitionServer       # noqa: E402
import synth                                                 # noqa: E402

RATE = 8000
PORT = 18988


async def stream(uri, pcm):
    results = []
    async with websockets.connect(uri, max_size=None) as ws:
        await ws.send(json.dumps({"type": "start", "version": 1, "uuid": "loop-uuid",
                                  "codec": "L16", "samplerate": RATE}))
        assert json.loads(await asyncio.wait_for(ws.recv(), 5)).get("type") == "ready"
        chunk = int(RATE * 0.02)
        for i in range(0, pcm.size, chunk):
            await ws.send(pcm[i:i + chunk].astype("<i2").tobytes())
        await ws.send(json.dumps({"type": "stop"}))
        try:
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), 3))
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
        samples = os.path.join(tmp, "samples")
        capture = os.path.join(tmp, "capture")
        lib = SampleLibrary(samples_dir=samples)  # empty
        server = RecognitionServer(lib, capture_dir=capture)
        uri = f"ws://127.0.0.1:{PORT}/"

        clip = synth.announcement(seed=1)
        stream_clip = synth.with_silence(clip, lead_ms=300, tail_ms=500)

        async with websockets.serve(server.handle, "127.0.0.1", PORT, max_size=None):
            # 1) unmatched -> prompt + captured
            print("== step 1: stream to empty library (expect prompt + capture) ==")
            res = await stream(uri, stream_clip)
            for r in res:
                print(f"  RESULT {r}")
            if any(r.get("tone") == "prompt" for r in res):
                print("  PASS (returned prompt)")
            else:
                print("  FAIL (expected prompt)"); rc = 1

            caps = [f for f in os.listdir(capture) if f.endswith(".wav")]
            print(f"  captured files: {caps}")
            if not caps:
                print("  FAIL (nothing captured)"); rc = 1; return rc
            print("  PASS (segment captured for labeling)")

            # 2) label the captured clip into the library
            print("== step 2: promote captured clip as 空号 ==")
            library.promote(samples, os.path.join(capture, caps[0]),
                            name="konghao_yidong", alias="does not exist", category="空号")
            print(f"  library now: {library.list_samples(samples)}")

            # 3) reload library, stream a degraded copy -> should match
            print("== step 3: reload library, stream degraded clip (expect match 空号) ==")
            server.library.load(samples)
            degraded = synth.with_silence(synth.degrade(clip, gain=0.5, noise=150),
                                          lead_ms=300, tail_ms=500)
            res2 = await stream(uri, degraded)
            for r in res2:
                print(f"  RESULT {r}")
            matched = [r for r in res2 if r.get("tone") == "sample"
                       and r.get("alias") == "does not exist" and r.get("accuracy") == "ACCURACY"]
            if matched:
                print("  PASS (now matched 空号 with ACCURACY)")
            else:
                print("  FAIL (still not matched after labeling)"); rc = 1

    print("ALL PASSED" if rc == 0 else "SOME FAILED")
    return rc


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
