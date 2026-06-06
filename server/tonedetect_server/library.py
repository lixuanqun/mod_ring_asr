"""样本库管理: 入库 / 列表 / 删除 / 提升(从待标注回流目录正式入库).

样本库 = 一个目录, 含 samples.json 索引与若干 8kHz/16bit 单声道 WAV.
入库时自动转单声道并重采样到目标采样率, 保证库内样本一致.
"""
from __future__ import annotations

import json
import os
import shutil

import numpy as np

from . import audio, states

TARGET_RATE = 8000


def resample_linear(pcm: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    if src_rate == dst_rate or pcm.size == 0:
        return pcm
    n_dst = int(round(pcm.size * dst_rate / src_rate))
    if n_dst < 1:
        n_dst = 1
    xs = np.linspace(0.0, pcm.size - 1, n_dst)
    i0 = np.floor(xs).astype(int)
    i1 = np.minimum(i0 + 1, pcm.size - 1)
    frac = xs - i0
    out = pcm[i0] * (1.0 - frac) + pcm[i1] * frac
    return out.astype(np.int16)


def index_path(samples_dir: str) -> str:
    return os.path.join(samples_dir, "samples.json")


def load_index(samples_dir: str) -> list[dict]:
    path = index_path(samples_dir)
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_index(samples_dir: str, entries: list[dict]) -> None:
    with open(index_path(samples_dir), "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


def add_sample(samples_dir: str, wav_path: str, name: str,
               alias: str = "", category: str = "", rate: int = TARGET_RATE,
               strict: bool = False) -> dict:
    """把 wav_path 转 8k 单声道入库为样本 name. 已存在同名则覆盖.

    alias/category 会按标准状态表(states.py)归一化: 给出其一即可补全另一.
    strict=True 时,不在标准表中的状态会抛错(避免样本库标签发散)。
    """
    os.makedirs(samples_dir, exist_ok=True)

    st = states.normalize(category=category, alias=alias)
    if st is not None:
        alias, category = st.alias, st.name
    elif strict and (alias or category):
        raise ValueError(f"alias/category 不在标准状态表中: alias={alias!r} category={category!r}")

    pcm, src_rate = audio.read_wav_mono16(wav_path)
    pcm = resample_linear(pcm, src_rate, rate)

    dest_file = f"{name}.wav"
    audio.write_wav_mono16(os.path.join(samples_dir, dest_file), pcm, rate)

    entries = [e for e in load_index(samples_dir) if e.get("name") != name]
    entry = {"file": dest_file, "name": name, "alias": alias, "category": category}
    if st is not None:
        entry["id"] = st.id
    entries.append(entry)
    save_index(samples_dir, entries)
    return entry


def list_samples(samples_dir: str) -> list[dict]:
    return load_index(samples_dir)


def remove_sample(samples_dir: str, name: str) -> bool:
    entries = load_index(samples_dir)
    keep, removed = [], None
    for e in entries:
        if e.get("name") == name:
            removed = e
        else:
            keep.append(e)
    if removed is None:
        return False
    wav = os.path.join(samples_dir, removed.get("file", ""))
    if os.path.isfile(wav):
        os.remove(wav)
    save_index(samples_dir, keep)
    return True


def promote(samples_dir: str, captured_wav: str, name: str,
            alias: str = "", category: str = "", remove_source: bool = True,
            rate: int = TARGET_RATE) -> dict:
    """把回流目录里一个未命中录音正式入库, 并清理其 sidecar."""
    entry = add_sample(samples_dir, captured_wav, name, alias, category, rate)
    if remove_source:
        for p in (captured_wav, os.path.splitext(captured_wav)[0] + ".json"):
            if os.path.isfile(p):
                os.remove(p)
    return entry
