"""确定性合成 "语音提示音" 片段, 用于测试指纹匹配与 VAD (不依赖真实录音)."""
from __future__ import annotations

import numpy as np

RATE = 8000


def announcement(seed: int, dur_s: float = 1.6, rate: int = RATE) -> np.ndarray:
    """模拟一段语音提示: 若干音节 (不同基频 + 谐波 + 音节包络)."""
    rng = np.random.default_rng(seed)
    n = int(dur_s * rate)
    t = np.arange(n) / rate
    sig = np.zeros(n)
    nseg = 6
    seglen = n // nseg
    base = rng.uniform(250, 1200, nseg)
    for i in range(nseg):
        s = i * seglen
        e = (i + 1) * seglen if i < nseg - 1 else n
        tt = t[s:e]
        f0 = base[i]
        seg = (np.sin(2 * np.pi * f0 * tt)
               + 0.5 * np.sin(2 * np.pi * 2 * f0 * tt)
               + 0.3 * np.sin(2 * np.pi * 3 * f0 * tt))
        seg *= np.hanning(len(tt))
        sig[s:e] = seg
    sig = sig / (np.max(np.abs(sig)) + 1e-9)
    return (sig * 8000).astype(np.int16)


def degrade(pcm: np.ndarray, gain: float = 0.5, noise: float = 200.0, seed: int = 7) -> np.ndarray:
    """模拟线路: 改变增益 + 叠加噪声 (验证指纹的增益/噪声鲁棒性)."""
    rng = np.random.default_rng(seed)
    x = pcm.astype(np.float64) * gain + rng.normal(0.0, noise, pcm.size)
    np.clip(x, -32768, 32767, out=x)
    return x.astype(np.int16)


def with_silence(pcm: np.ndarray, lead_ms: int = 400, tail_ms: int = 400, rate: int = RATE) -> np.ndarray:
    lead = np.zeros(int(lead_ms * rate / 1000), np.int16)
    tail = np.zeros(int(tail_ms * rate / 1000), np.int16)
    return np.concatenate([lead, pcm, tail])
