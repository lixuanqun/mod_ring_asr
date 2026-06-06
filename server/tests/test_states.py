"""单测: 全状态(da2 id 2-20)ASR 关键词分类 + 优先级排序."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tonedetect_server import states                       # noqa: E402
from tonedetect_server.asr import KeywordClassifier        # noqa: E402

# 每个状态一条代表性转写 -> 期望 state id
CASES: list[tuple[str, int]] = [
    ("您拨打的电话已关机", 2),
    ("您拨打的号码是空号", 3),
    ("您拨打的电话已停机", 4),
    ("您拨打的用户正在通话中", 5),
    ("用户暂不方便接听已拒接", 6),
    ("您拨打的电话暂时无法接通", 7),
    ("您的电话已暂停服务", 8),
    ("用户正忙", 9),
    ("您拨打的号码有误请核对后再拨", 10),
    ("您拨打的电话已设置呼入限制", 11),
    ("您好您已进入语音信箱请留言", 12),
    ("您拨打的电话呼叫转移失败", 13),
    ("对不起网络忙", 14),
    ("您拨打的电话无人接听", 15),
    ("您拨打的电话已欠费", 16),
    ("您拨打的电话暂时无法接听", 17),
    ("该用户已改号新号码为", 18),
    ("线路故障无法接通", 19),     # 含"无法接通", 但优先级 19 在 7 之前
    ("请稍后再拨", 20),
]


def test_all_states_classified():
    clf = KeywordClassifier()
    ok = True
    for text, sid in CASES:
        want = states.by_id(sid)
        got = clf.classify(text)
        status = "ok" if got == (want.name, want.alias) else "MISMATCH"
        if status != "ok":
            ok = False
        print(f"  [{sid:>2}] '{text}' -> {got} expect ({want.name},{want.alias}) [{status}]")
    assert ok, "some states mis-classified"


def test_priority_ordering():
    clf = KeywordClassifier()
    # "通话中" + "稍后再拨" 同现 -> 应判通话中(5), 不被稍后再拨(20)抢
    assert clf.classify("正在通话中,请稍后再拨") == ("正在通话中", "hold on")
    # "线路故障" + "无法接通" 同现 -> 线路故障(19) 优先
    assert clf.classify("线路故障,暂时无法接通") == ("线路故障", "line fault")
    # 无关文本 -> None
    assert clf.classify("今天天气不错") is None
    print("  ordering OK")


def test_table_integrity():
    assert len(states.STATES) == 19
    assert {s.id for s in states.STATES} == set(range(2, 21))
    assert len(states.ORDER) == 19 and set(states.ORDER) == set(range(2, 21))
    assert states.by_alias("does not exist").name == "空号"
    assert states.normalize(category="关机").alias == "power off"
    assert states.normalize(alias="busy now").name == "用户正忙"
    print("  table integrity OK (19 states, ids 2-20)")


def run():
    rc = 0
    for t in (test_all_states_classified, test_priority_ordering, test_table_integrity):
        print(f"== {t.__name__} ==")
        try:
            t(); print("  PASS")
        except AssertionError as e:
            print(f"  FAIL: {e}"); rc = 1
    print("ALL PASSED" if rc == 0 else "SOME FAILED")
    return rc


if __name__ == "__main__":
    sys.exit(run())
