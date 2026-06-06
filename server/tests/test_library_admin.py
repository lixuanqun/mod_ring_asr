"""单测: 样本库管理 (add/list/remove/promote) + 重采样, 无网络."""
from __future__ import annotations

import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tonedetect_server import audio, library                # noqa: E402
import synth                                                 # noqa: E402

RATE = 8000


def test_add_list_remove():
    with tempfile.TemporaryDirectory() as tmp:
        samples = os.path.join(tmp, "samples")
        wav = os.path.join(tmp, "clip.wav")
        audio.write_wav_mono16(wav, synth.announcement(seed=1), RATE)

        library.add_sample(samples, wav, name="konghao", alias="does not exist", category="空号")
        entries = library.list_samples(samples)
        print(f"  after add: {entries}")
        assert len(entries) == 1 and entries[0]["alias"] == "does not exist"
        assert os.path.isfile(os.path.join(samples, "konghao.wav"))

        # overwrite same name -> still 1
        library.add_sample(samples, wav, name="konghao", alias="does not exist", category="空号")
        assert len(library.list_samples(samples)) == 1

        assert library.remove_sample(samples, "konghao") is True
        assert library.list_samples(samples) == []
        assert not os.path.isfile(os.path.join(samples, "konghao.wav"))
        print("  add/list/remove OK")


def test_resample_on_add():
    with tempfile.TemporaryDirectory() as tmp:
        samples = os.path.join(tmp, "samples")
        wav = os.path.join(tmp, "clip16k.wav")
        # write a 16kHz clip; library should down-sample to 8k on add
        audio.write_wav_mono16(wav, synth.announcement(seed=4, rate=16000), 16000)
        library.add_sample(samples, wav, name="x", alias="a", category="c")
        pcm, rate = audio.read_wav_mono16(os.path.join(samples, "x.wav"))
        print(f"  stored sample rate = {rate}")
        assert rate == RATE, "sample must be stored at 8kHz"


def test_promote_from_capture():
    with tempfile.TemporaryDirectory() as tmp:
        samples = os.path.join(tmp, "samples")
        capture = os.path.join(tmp, "capture")
        os.makedirs(capture)
        cap_wav = os.path.join(capture, "uuid_123.wav")
        cap_json = os.path.join(capture, "uuid_123.json")
        audio.write_wav_mono16(cap_wav, synth.announcement(seed=2), RATE)
        with open(cap_json, "w") as f:
            f.write('{"uuid":"123"}')

        library.promote(samples, cap_wav, name="guanji", alias="power off", category="关机")
        entries = library.list_samples(samples)
        print(f"  after promote: {entries}")
        assert len(entries) == 1 and entries[0]["category"] == "关机"
        # source + sidecar cleaned up
        assert not os.path.isfile(cap_wav) and not os.path.isfile(cap_json)
        print("  promote OK (source cleaned)")


def run():
    rc = 0
    for t in (test_add_list_remove, test_resample_on_add, test_promote_from_capture):
        print(f"== {t.__name__} ==")
        try:
            t(); print("  PASS")
        except AssertionError as e:
            print(f"  FAIL: {e}"); rc = 1
    print("ALL PASSED" if rc == 0 else "SOME FAILED")
    return rc


if __name__ == "__main__":
    sys.exit(run())
