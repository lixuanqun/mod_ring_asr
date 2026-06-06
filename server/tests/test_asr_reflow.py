"""端到端: ASR 兜底 + 自动回流补库.

1. 空样本库 + 开启 ASR(stub 返回 "已关机") + autolearn
2. 流式推一段提示音 -> 指纹未命中 -> ASR 兜底归类为 关机/power off (tone=asr)
   并自动把该段补进样本库、热重载
3. 再推该提示音(劣化版) -> 这次走指纹快路径直接命中 (tone=sample, 关机)
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

from tonedetect_server.asr import ASRFallback, StubASR              # noqa: E402
from tonedetect_server.matcher import SampleLibrary                 # noqa: E402
from tonedetect_server.server import RecognitionServer              # noqa: E402
import synth                                                        # noqa: E402

RATE = 8000
PORT = 18999


async def stream(uri, pcm):
    results = []
    async with websockets.connect(uri, max_size=None) as ws:
        await ws.send(json.dumps({"type": "start", "version": 1, "uuid": "asr-uuid",
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
        lib = SampleLibrary(samples_dir=samples)  # empty
        asr = ASRFallback(StubASR(text="您拨打的电话已关机"))
        server = RecognitionServer(lib, asr=asr, autolearn=True, samples_dir=samples)
        uri = f"ws://127.0.0.1:{PORT}/"

        clip = synth.announcement(seed=5)
        async with websockets.serve(server.handle, "127.0.0.1", PORT, max_size=None):
            print("== step 1: empty library, ASR fallback (expect tone=asr 关机) ==")
            res = await stream(uri, synth.with_silence(clip, 300, 500))
            for r in res:
                print(f"  RESULT {r}")
            asr_hit = [r for r in res if r.get("tone") == "asr" and r.get("alias") == "power off"]
            if asr_hit:
                print("  PASS (ASR classified as 关机/power off)")
            else:
                print("  FAIL (ASR fallback did not classify)"); rc = 1

            print(f"  library after autolearn: {len(server.library.samples)} sample(s)")
            if len(server.library.samples) < 1:
                print("  FAIL (autolearn did not add a sample)"); rc = 1; return rc
            print("  PASS (segment auto-learned into library)")

            print("== step 2: re-stream degraded clip (expect fingerprint match tone=sample) ==")
            degraded = synth.with_silence(synth.degrade(clip, gain=0.5, noise=150), 300, 500)
            res2 = await stream(uri, degraded)
            for r in res2:
                print(f"  RESULT {r}")
            fp_hit = [r for r in res2 if r.get("tone") == "sample" and r.get("alias") == "power off"]
            if fp_hit:
                print("  PASS (now matched by fingerprint fast-path)")
            else:
                print("  FAIL (fingerprint did not match after autolearn)"); rc = 1

    print("ALL PASSED" if rc == 0 else "SOME FAILED")
    return rc


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
