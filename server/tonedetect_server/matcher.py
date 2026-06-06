"""样本库 + 指纹匹配引擎.

样本库 = 一个目录, 内含若干参考提示音 WAV, 以及描述其标签的 samples.json:

  [
    {"file": "konghao.wav", "name": "konghao_yidong",
     "alias": "does not exist", "category": "空号"},
    ...
  ]

加载时为每个样本预计算指纹. 查询时对输入语音段算指纹, 找最近邻样本,
按相似度分级为 ACCURACY / INACCURACY / LOOSE.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

import numpy as np

from . import audio, fingerprint


@dataclass
class Sample:
    name: str
    alias: str
    category: str
    fp: np.ndarray


@dataclass
class MatchResult:
    tone: str          # sample | prompt
    score: float
    accuracy: str      # ACCURACY | INACCURACY | LOOSE
    name: str = ""
    alias: str = ""
    category: str = ""


class SampleLibrary:
    def __init__(self, samples_dir: str | None = None,
                 accuracy_threshold: float = 0.75,
                 inaccuracy_threshold: float = 0.60,
                 rate: int = 8000):
        self.rate = rate
        self.accuracy_threshold = accuracy_threshold
        self.inaccuracy_threshold = inaccuracy_threshold
        self.samples: list[Sample] = []
        if samples_dir:
            self.load(samples_dir)

    def load(self, samples_dir: str) -> int:
        self.samples = []
        index = os.path.join(samples_dir, "samples.json")
        if not os.path.isfile(index):
            return 0
        with open(index, "r", encoding="utf-8") as f:
            entries = json.load(f)
        for e in entries:
            path = os.path.join(samples_dir, e["file"])
            if not os.path.isfile(path):
                continue
            pcm, rate = audio.read_wav_mono16(path)
            fp = fingerprint.compute_fingerprint(pcm, rate)
            if fp is None:
                continue
            self.samples.append(Sample(
                name=e.get("name", e["file"]),
                alias=e.get("alias", ""),
                category=e.get("category", ""),
                fp=fp,
            ))
        return len(self.samples)

    def match(self, pcm: np.ndarray, rate: int | None = None) -> MatchResult:
        rate = rate or self.rate
        fp = fingerprint.compute_fingerprint(pcm, rate)
        if fp is None or not self.samples:
            return MatchResult(tone="prompt", score=0.0, accuracy="LOOSE")

        best, best_score = None, -1.0
        for s in self.samples:
            sc = fingerprint.similarity(fp, s.fp)
            if sc > best_score:
                best, best_score = s, sc

        if best_score >= self.accuracy_threshold:
            acc = "ACCURACY"
        elif best_score >= self.inaccuracy_threshold:
            acc = "INACCURACY"
        else:
            acc = "LOOSE"

        if acc == "LOOSE":
            # not confident enough -> treat as an un-matched voice prompt
            return MatchResult(tone="prompt", score=best_score, accuracy=acc)

        return MatchResult(tone="sample", score=best_score, accuracy=acc,
                           name=best.name, alias=best.alias, category=best.category)
