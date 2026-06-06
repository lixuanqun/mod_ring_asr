"""端到端: 指纹 INACCURACY + ASR 交叉校验.

构造指纹候选落在 INACCURACY 区间(把 accuracy 阈值调高使真实劣化匹配≈0.8 落入
[inaccuracy, accuracy)),再用 ASR 复核:
  - ASR 与指纹候选一致 -> 升为 ACCURACY (confirmed_by=asr)
  - ASR 不一致 -> 保持 INACCURACY(不误升)
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile

import websockets

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tonedetect_server import audio, library                # noqa: E402
from tonedetect_server.asr import ASRFallback, StubASR       # noqa: E402
from tonedetect_server.matcher import SampleLibrary          # noqa: E402
from tonedetect_server.server import RecognitionServer       # noqa: E402
import synth                                                 # noqa: E402

RATE = 8000


async def stream(uri, pcm):
    results = []
    async with websockets.connect(uri, max_size=None) as ws:
        await ws.send(json.dumps({"type": "start", "version": 1, "uuid": "x",
                                  "codec": "L16", "samplerate": RATE}))
        assert json.loads(await asyncio.wait_for(ws.recv(), 5)).get("type") == "ready"
        chunk = int(RATE * 0.02)
        for i in range(0, pcm.size, chunk):
            await ws.send(pcm[i:i + chunk].astype("<i2").tobytes())
        await ws.send(json.dumps({"type": "stop"}))
        try:
            while True:
                m = json.loads(await asyncio.wait_for(ws.recv(), 3))
                if m.get("type") == "result":
                    results.append(m)
                elif m.get("type") == "fin":
                    break
        except (asyncio.TimeoutError, websockets.ConnectionClosed):
            pass
    return results


async def run_case(port, asr_text, expect_accuracy, expect_confirmed):
    with tempfile.TemporaryDirectory() as tmp:
        samples = os.path.join(tmp, "samples")
        clip = synth.announcement(seed=1)
        audio.write_wav_mono16(os.path.join(tmp, "s.wav"), clip, RATE)
        os.makedirs(samples, exist_ok=True)
        library.add_sample(samples, os.path.join(tmp, "s.wav"),
                           name="konghao", category="空号")  # alias 由标准表补全
        # 阈值调高 -> 真实劣化匹配(≈0.8)落入 INACCURACY 区间
        lib = SampleLibrary(samples_dir=samples, accuracy_threshold=0.99, inaccuracy_threshold=0.60)
        server = RecognitionServer(lib, asr=ASRFallback(StubASR(text=asr_text)))
        uri = f"ws://127.0.0.1:{port}/"
        async with websockets.serve(server.handle, "127.0.0.1", port, max_size=None):
            degraded = synth.with_silence(synth.degrade(clip, gain=0.5, noise=150), 300, 500)
            res = await stream(uri, degraded)
        sample_res = [r for r in res if r.get("tone") == "sample"]
        assert sample_res, f"expected a sample candidate, got {res}"
        r = sample_res[0]
        print(f"  asr='{asr_text}' -> accuracy={r.get('accuracy')} confirmed_by={r.get('confirmed_by')}")
        assert r.get("accuracy") == expect_accuracy, f"accuracy {r.get('accuracy')} != {expect_accuracy}"
        assert (r.get("confirmed_by") == "asr") == expect_confirmed
        return r


async def main():
    rc = 0
    print("== case 1: ASR agrees (空号) -> upgrade INACCURACY to ACCURACY ==")
    try:
        await run_case(19001, "您拨打的号码是空号", "ACCURACY", True)
        print("  PASS")
    except AssertionError as e:
        print(f"  FAIL: {e}"); rc = 1

    print("== case 2: ASR disagrees (关机) -> stays INACCURACY ==")
    try:
        await run_case(19002, "您拨打的电话已关机", "INACCURACY", False)
        print("  PASS")
    except AssertionError as e:
        print(f"  FAIL: {e}"); rc = 1

    print("ALL PASSED" if rc == 0 else "SOME FAILED")
    return rc


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
