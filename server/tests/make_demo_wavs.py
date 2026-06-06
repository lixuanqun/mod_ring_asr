"""生成跨语言端到端演示用的 WAV:
  <out>/samples/konghao.wav + samples.json   (服务端样本库)
  <out>/query_match.wav                       (样本的增益+噪声劣化版, 应命中)
  <out>/query_other.wav                       (不同片段, 不应命中)

用法: python make_demo_wavs.py <out_dir>
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tonedetect_server import audio          # noqa: E402
import synth                                  # noqa: E402

RATE = 8000


def main(out: str):
    samples = os.path.join(out, "samples")
    os.makedirs(samples, exist_ok=True)

    clip_a = synth.announcement(seed=1)
    audio.write_wav_mono16(os.path.join(samples, "konghao.wav"), clip_a, RATE)
    with open(os.path.join(samples, "samples.json"), "w", encoding="utf-8") as f:
        json.dump([{"file": "konghao.wav", "name": "konghao_yidong",
                    "alias": "does not exist", "category": "空号"}], f, ensure_ascii=False)

    match = synth.with_silence(synth.degrade(clip_a, gain=0.5, noise=150), lead_ms=300, tail_ms=500)
    audio.write_wav_mono16(os.path.join(out, "query_match.wav"), match, RATE)

    other = synth.with_silence(synth.announcement(seed=2), lead_ms=300, tail_ms=500)
    audio.write_wav_mono16(os.path.join(out, "query_other.wav"), other, RATE)

    print(f"wrote {samples}/konghao.wav (+samples.json), {out}/query_match.wav, {out}/query_other.wav")


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/td_demo"
    main(out)
