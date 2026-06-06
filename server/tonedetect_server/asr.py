"""阶段3: ASR 兜底.

对样本库未命中(prompt)的语音段,转写成文字再按关键词归类为号码状态。
用于覆盖样本库还没收录的提示音(措辞/运营商差异),并可把这些段自动回流补库,
使下次走更快、更准的指纹匹配。

ASR 引擎是**可插拔**的:
  - `ASREngine` 是接口,生产环境接入真实引擎(本地 Whisper / 云端 ASR)。
  - `StubASR` 仅用于测试/演示,返回预置文本(合成音无法被真实 ASR 转写)。
关键词分类器 `KeywordClassifier` 是确定性逻辑,可独立单测。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import states


@dataclass
class AsrResult:
    text: str
    category: str
    alias: str


class KeywordClassifier:
    """转写文本 -> (category, alias)。覆盖 da2 全部号码状态(id 2-20)。

    规则与优先级来自 states.py 的标准表(`ordered_states()`,先具体后宽泛,
    "稍后再拨"放最末避免把"通话中,请稍后再拨"误判)。
    """

    def classify(self, text: str) -> tuple[str, str] | None:
        if not text:
            return None
        for st in states.ordered_states():
            if any(k in text for k in st.keywords):
                return st.name, st.alias
        return None


class ASREngine:
    """ASR 引擎接口。生产环境实现 transcribe()。"""

    def transcribe(self, pcm: np.ndarray, rate: int) -> str:  # pragma: no cover - interface
        raise NotImplementedError


class StubASR(ASREngine):
    """测试/演示用:返回预置文本(可固定,或按调用顺序返回)。"""

    def __init__(self, text: str | None = None, texts: list[str] | None = None):
        self._text = text
        self._texts = list(texts) if texts else None
        self._i = 0

    def transcribe(self, pcm: np.ndarray, rate: int) -> str:
        if self._texts is not None:
            t = self._texts[self._i] if self._i < len(self._texts) else ""
            self._i += 1
            return t
        return self._text or ""


class ASRFallback:
    """把"转写 + 归类"组合起来。"""

    def __init__(self, engine: ASREngine, classifier: KeywordClassifier | None = None):
        self.engine = engine
        self.classifier = classifier or KeywordClassifier()

    def recognize(self, pcm: np.ndarray, rate: int) -> AsrResult | None:
        text = (self.engine.transcribe(pcm, rate) or "").strip()
        if not text:
            return None
        hit = self.classifier.classify(text)
        if not hit:
            return None
        category, alias = hit
        return AsrResult(text=text, category=category, alias=alias)


def create_asr(name: str | None) -> ASREngine | None:
    """工厂:按名字创建 ASR 引擎。生产环境在此接入真实引擎。"""
    if not name or name in ("none", "off"):
        return None
    if name == "stub":
        # 仅占位,真实部署请替换为下面的真实引擎分支
        return StubASR(text="")
    # 例:
    #   if name == "whisper":
    #       from .asr_whisper import WhisperASR
    #       return WhisperASR(model="small")
    raise ValueError(f"unknown ASR engine: {name} (implement it in asr.create_asr)")
