"""单测: 音频指纹匹配 + VAD 切片 (无网络)."""
from __future__ import annotations

import json
import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tonedetect_server import audio, fingerprint            # noqa: E402
from tonedetect_server.matcher import SampleLibrary         # noqa: E402
from tonedetect_server.vad import StreamingSegmenter        # noqa: E402
import synth                                                # noqa: E402

RATE = 8000


def build_library(tmp: str) -> SampleLibrary:
    clip_a = synth.announcement(seed=1)
    audio.write_wav_mono16(os.path.join(tmp, "konghao.wav"), clip_a, RATE)
    entries = [{"file": "konghao.wav", "name": "konghao_yidong",
                "alias": "does not exist", "category": "空号"}]
    with open(os.path.join(tmp, "samples.json"), "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False)
    return SampleLibrary(samples_dir=tmp)


def test_fingerprint_gain_noise_robust():
    a = synth.announcement(seed=1)
    fa = fingerprint.compute_fingerprint(a, RATE)
    fa2 = fingerprint.compute_fingerprint(synth.degrade(a, gain=0.4, noise=150), RATE)
    b = fingerprint.compute_fingerprint(synth.announcement(seed=2), RATE)
    sim_same = fingerprint.similarity(fa, fa2)
    sim_diff = fingerprint.similarity(fa, b)
    print(f"  sim(A, degraded A) = {sim_same:.3f}")
    print(f"  sim(A, B)          = {sim_diff:.3f}")
    assert sim_same >= 0.75, f"expected robust match >=0.75, got {sim_same:.3f}"
    assert sim_same > sim_diff + 0.2, "same-clip sim must clearly exceed different-clip sim"


def test_library_match_and_reject():
    with tempfile.TemporaryDirectory() as tmp:
        lib = build_library(tmp)
        assert len(lib.samples) == 1

        a = synth.announcement(seed=1)
        m_same = lib.match(synth.degrade(a, gain=0.5, noise=200), RATE)
        print(f"  degraded-A -> tone={m_same.tone} alias='{m_same.alias}' "
              f"score={m_same.score:.3f} acc={m_same.accuracy}")
        assert m_same.tone == "sample", "degraded A should match the sample"
        assert m_same.alias == "does not exist"
        assert m_same.accuracy == "ACCURACY"

        b = synth.announcement(seed=2)
        m_diff = lib.match(b, RATE)
        print(f"  clip-B     -> tone={m_diff.tone} score={m_diff.score:.3f} acc={m_diff.accuracy}")
        assert m_diff.tone != "sample" or m_diff.alias != "does not exist", \
            "different clip must not be matched as the空号 sample"
        assert m_diff.score < m_same.score


def test_vad_segments_one_announcement():
    a = synth.announcement(seed=3, dur_s=1.2)
    stream = synth.with_silence(a, lead_ms=400, tail_ms=400)
    seg = StreamingSegmenter(rate=RATE)
    segments = []
    # feed in 20ms chunks like the real stream
    chunk = int(RATE * 0.02)
    for i in range(0, stream.size, chunk):
        segments += seg.feed(stream[i:i + chunk])
    segments += seg.flush()
    print(f"  segments found: {len(segments)}")
    for s in segments:
        print(f"    [{s.begin_ms}-{s.end_ms} ms] {s.pcm.size} samples")
    assert len(segments) == 1, f"expected 1 speech segment, got {len(segments)}"
    s = segments[0]
    assert 300 <= s.begin_ms <= 500, f"segment should start ~400ms, got {s.begin_ms}"
    assert s.pcm.size >= int(RATE * 1.0), "segment should contain the ~1.2s announcement"


def run():
    tests = [test_fingerprint_gain_noise_robust, test_library_match_and_reject,
             test_vad_segments_one_announcement]
    rc = 0
    for t in tests:
        print(f"== {t.__name__} ==")
        try:
            t()
            print("  PASS")
        except AssertionError as e:
            print(f"  FAIL: {e}")
            rc = 1
    print("ALL PASSED" if rc == 0 else "SOME FAILED")
    return rc


if __name__ == "__main__":
    sys.exit(run())
