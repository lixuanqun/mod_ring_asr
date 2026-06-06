"""单测: ASR 关键词分类器 + ASRFallback (无网络, 无真实ASR)."""
from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tonedetect_server.asr import ASRFallback, KeywordClassifier, StubASR   # noqa: E402

CASES = [
    ("您拨打的电话已关机", "关机", "power off"),
    ("您拨打的号码是空号", "空号", "does not exist"),
    ("您拨打的电话已停机", "停机", "out of service"),
    ("您拨打的用户正在通话中请稍后再拨", "正在通话中", "hold on"),
    ("对不起您拨打的电话暂时无法接通", "无法接通", "is not reachable"),
    ("您好您已进入语音信箱请留言", "来电提醒", "call reminder"),
    ("您拨打的电话已暂停服务", "暂停服务", "not in service"),
]


def test_classifier():
    clf = KeywordClassifier()
    ok = True
    for text, cat, alias in CASES:
        hit = clf.classify(text)
        got = hit if hit else ("None", "None")
        status = "ok" if hit == (cat, alias) else "MISMATCH"
        if hit != (cat, alias):
            ok = False
        print(f"  '{text}' -> {got} [{status}]")
    assert ok, "some transcripts mis-classified"
    # negative: unrelated text -> no class
    assert clf.classify("今天天气不错") is None
    print("  unrelated text -> None (ok)")


def test_fallback_recognize():
    asr = ASRFallback(StubASR(text="您拨打的电话已关机"))
    res = asr.recognize(np.zeros(8000, dtype=np.int16), 8000)
    print(f"  fallback -> {res}")
    assert res is not None and res.category == "关机" and res.alias == "power off"

    asr2 = ASRFallback(StubASR(text=""))   # empty transcript -> None
    assert asr2.recognize(np.zeros(100, dtype=np.int16), 8000) is None
    print("  empty transcript -> None (ok)")


def run():
    rc = 0
    for t in (test_classifier, test_fallback_recognize):
        print(f"== {t.__name__} ==")
        try:
            t(); print("  PASS")
        except AssertionError as e:
            print(f"  FAIL: {e}"); rc = 1
    print("ALL PASSED" if rc == 0 else "SOME FAILED")
    return rc


if __name__ == "__main__":
    sys.exit(run())
