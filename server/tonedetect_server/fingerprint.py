"""音频指纹: 把一段 PCM 压缩成增益无关、可比较的定长向量.

做法 (轻量, 仅依赖 numpy):
  1. 分帧 (32ms 窗 / 16ms 跳), 加汉宁窗, 取功率谱
  2. 在电话频带 (200-3400Hz) 上聚合成 N 个对数频带能量
  3. log 压缩 + 逐帧去均值  -> 增益/音量无关
  4. 时间轴线性重采样到固定帧数 -> 不同时长可比
  5. 展平 + L2 归一化 -> 余弦相似度即点积

这种指纹对音量变化和轻度噪声鲁棒, 同时保留了提示音的时频结构
(可区分 "已关机" / "是空号" 等不同语音提示).
"""
from __future__ import annotations

import numpy as np

N_BANDS = 16
N_FRAMES = 32
WIN_MS = 32
HOP_MS = 16
BAND_LO = 200.0
BAND_HI = 3400.0


def compute_fingerprint(pcm: np.ndarray, rate: int = 8000,
                        n_bands: int = N_BANDS, n_frames: int = N_FRAMES) -> np.ndarray | None:
    """pcm: 1-D int16/float ndarray. 返回 L2 归一化的指纹向量, 空输入返回 None."""
    if pcm is None or pcm.size == 0:
        return None
    x = pcm.astype(np.float64)

    win = max(1, int(WIN_MS * rate / 1000))
    hop = max(1, int(HOP_MS * rate / 1000))
    if x.size < win:
        x = np.pad(x, (0, win - x.size))

    n = 1 + (x.size - win) // hop
    if n < 1:
        n = 1

    window = np.hanning(win)
    freqs = np.fft.rfftfreq(win, d=1.0 / rate)
    edges = np.logspace(np.log10(BAND_LO), np.log10(BAND_HI), n_bands + 1)
    band_idx = [np.where((freqs >= edges[b]) & (freqs < edges[b + 1]))[0] for b in range(n_bands)]

    spec = np.zeros((n, n_bands), dtype=np.float64)
    for i in range(n):
        seg = x[i * hop:i * hop + win]
        if seg.size < win:
            seg = np.pad(seg, (0, win - seg.size))
        mag = np.abs(np.fft.rfft(seg * window)) ** 2
        for b in range(n_bands):
            idx = band_idx[b]
            if idx.size:
                spec[i, b] = mag[idx].sum()

    spec = np.log1p(spec)
    # light temporal smoothing (3-frame moving average) suppresses additive noise
    if spec.shape[0] >= 3:
        kernel = np.ones(3) / 3.0
        spec = np.apply_along_axis(lambda c: np.convolve(c, kernel, mode="same"), 0, spec)
    # per-frame mean removal -> gain/volume invariance
    spec = spec - spec.mean(axis=1, keepdims=True)

    # resample time axis to fixed n_frames (linear interpolation)
    if n != n_frames:
        xs = np.linspace(0.0, n - 1, n_frames)
        i0 = np.floor(xs).astype(int)
        i1 = np.minimum(i0 + 1, n - 1)
        frac = (xs - i0)[:, None]
        spec = spec[i0] * (1.0 - frac) + spec[i1] * frac

    fp = spec.flatten()
    norm = np.linalg.norm(fp)
    if norm > 0:
        fp = fp / norm
    return fp


def similarity(a: np.ndarray, b: np.ndarray) -> float:
    """两个 L2 归一化指纹的余弦相似度 (= 点积), 范围约 [-1, 1]."""
    if a is None or b is None:
        return 0.0
    return float(np.dot(a, b))
