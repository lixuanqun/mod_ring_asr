"""WAV (mono 16-bit PCM) 读写辅助, 仅用标准库 wave + numpy."""
from __future__ import annotations

import wave

import numpy as np


def read_wav_mono16(path: str) -> tuple[np.ndarray, int]:
    """返回 (int16 ndarray, samplerate). 多声道取第 0 声道."""
    with wave.open(path, "rb") as w:
        rate = w.getframerate()
        ch = w.getnchannels()
        sw = w.getsampwidth()
        n = w.getnframes()
        raw = w.readframes(n)
    if sw != 2:
        raise ValueError(f"only 16-bit PCM supported, got sampwidth={sw}")
    data = np.frombuffer(raw, dtype="<i2")
    if ch > 1:
        data = data[::ch]
    return data.copy(), rate


def write_wav_mono16(path: str, pcm: np.ndarray, rate: int) -> None:
    pcm = np.asarray(pcm, dtype="<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
