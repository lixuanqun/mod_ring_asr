"""号码状态标准表(对齐顶顶通 da2 的 id/name/alias),作为全局单一来源。

样本库的 category/alias、ASR 关键词分类、文档展示都引用这里,保证一致。
另含信号音(由本地 DSP 或服务粗分得到)。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class State:
    id: int
    name: str          # 中文名(category)
    alias: str         # 英文别名
    description: str
    keywords: tuple[str, ...] = field(default=())  # ASR 转写命中关键词


# da2 号码状态表(id 2-20)。keywords 顺序无关,匹配优先级由 ORDER 控制。
STATES: list[State] = [
    State(2,  "关机",        "power off",            "关机",
          ("关机", "已关机")),
    State(3,  "空号",        "does not exist",       "空号",
          ("空号", "是空号", "不存在", "查无此号", "没有这个号码", "是错误的")),
    State(4,  "停机",        "out of service",       "停机(欠费很久给停机)",
          ("停机", "已停机")),
    State(5,  "正在通话中",  "hold on",              "正在通话中(多数交换机用户拒接/无应答也返回此)",
          ("正在通话中", "通话中")),
    State(6,  "用户拒接",    "not convenient",       "用户拒接",
          ("已拒接", "拒接", "暂不方便接听")),
    State(7,  "无法接通",    "is not reachable",     "无法接通(可能没信号)",
          ("无法接通", "暂时无法接通", "不在服务区", "无法转接")),
    State(8,  "暂停服务",    "not in service",       "暂停服务(刚欠费被限制呼入)",
          ("暂停服务", "暂停使用")),
    State(9,  "用户正忙",    "busy now",             "用户正忙(未开来电等待且在通话中)",
          ("用户正忙", "正忙", "占线")),
    State(10, "拨号方式不正确", "not a local number", "拨号方式不正确(一般需加0)",
          ("拨号方式不正确", "号码有误", "请核对后再拨", "拨号有误", "您拨打的号码有误")),
    State(11, "呼入限制",    "barring of incoming",  "呼入限制(未开语音/欠费/暂停服务等)",
          ("呼入限制", "限制呼入", "已设置呼入限制")),
    State(12, "来电提醒",    "call reminder",        "各类秘书服务/来电提醒/语音信箱/语音留言",
          ("语音信箱", "语音留言", "请留言", "来电提醒", "秘书", "通信助理", "助理服务")),
    State(13, "呼叫转移失败", "forwarded",           "呼叫转移失败(转移目标呼叫失败)",
          ("呼叫转移", "已转移", "转移失败")),
    State(14, "网络忙",      "line is busy",         "网络忙(一般是局端故障)",
          ("网络忙", "系统忙", "网络正忙")),
    State(15, "无人接听",    "not answer",           "无人接听",
          ("无人接听", "无应答", "没有应答")),
    State(16, "欠费",        "defaulting",           "欠费(主叫或被叫欠费)",
          ("欠费", "余额不足", "已欠费")),
    State(17, "无法接听",    "cannot be connected",  "无法接听",
          ("无法接听", "暂时无法接听")),
    State(18, "改号",        "number change",        "改号(用户换号)",
          ("改号", "新号码", "号码已变更", "已改为")),
    State(19, "线路故障",    "line fault",           "线路不能呼出(如SIM卡欠费)",
          ("线路故障", "线路不能呼出", "线路忙")),
    State(20, "稍后再拨",    "redial later",         "各种稍后再拨提示",
          ("稍后再拨", "稍后再来电", "请稍后", "待会再拨")),
]

# 关键词匹配优先级(先具体后宽泛)。"稍后再拨"常附在其它提示后,放最末避免误判。
ORDER: list[int] = [2, 3, 4, 8, 11, 16, 18, 19, 13, 12, 10, 7, 17, 15, 14, 5, 9, 6, 20]

# 信号音(本地 DSP / 服务粗分)
SIGNAL_TONES = {
    "ringback":       "回铃音",
    "busy":           "忙音",
    "congestion":     "拥塞/快忙",
    "colorringback":  "彩铃(音乐)",
    "450hz":          "450Hz 嘟音",
    "silence":        "静音",
    "prompt":         "未识别语音提示",
    "other":          "非纯音(疑似彩铃/语音)",
}

_BY_ALIAS = {s.alias: s for s in STATES}
_BY_NAME = {s.name: s for s in STATES}
_BY_ID = {s.id: s for s in STATES}


def by_alias(alias: str) -> State | None:
    return _BY_ALIAS.get(alias)


def by_name(name: str) -> State | None:
    return _BY_NAME.get(name)


def by_id(sid: int) -> State | None:
    return _BY_ID.get(sid)


def ordered_states() -> list[State]:
    """按匹配优先级返回状态。"""
    return [_BY_ID[i] for i in ORDER if i in _BY_ID]


def normalize(category: str = "", alias: str = "") -> State | None:
    """根据 name 或 alias 归一到标准状态(供样本入库校验)。"""
    if alias and alias in _BY_ALIAS:
        return _BY_ALIAS[alias]
    if category and category in _BY_NAME:
        return _BY_NAME[category]
    return None
