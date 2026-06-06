"""流式能量 VAD 切片器.

按帧 (默认 20ms) 计算 RMS, 判定语音/静音; 连续语音帧构成一个语音段,
当语音后出现 >= hangover 的静音时, 该段结束并被提交识别 (模拟 da2 的
"停顿 ~200ms 即提交"). 跨多次 feed 调用维护状态.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Segment:
    pcm: np.ndarray
    begin_ms: int
    end_ms: int


class StreamingSegmenter:
    def __init__(self, rate: int = 8000, frame_ms: int = 20,
                 rms_threshold: float = 300.0, hangover_ms: int = 200,
                 min_segment_ms: int = 250, max_segment_ms: int = 8000):
        self.rate = rate
        self.frame_size = max(1, int(rate * frame_ms / 1000))
        self.frame_ms = frame_ms
        self.rms_threshold = rms_threshold
        self.hangover_frames = max(1, int(hangover_ms / frame_ms))
        self.min_frames = max(1, int(min_segment_ms / frame_ms))
        self.max_frames = max(1, int(max_segment_ms / frame_ms))

        self._buf = np.zeros(0, dtype=np.int16)
        self._in_speech = False
        self._seg_frames: list[np.ndarray] = []
        self._silence_run = 0
        self._seg_begin_ms = 0
        self._total_frames = 0

    def feed(self, pcm: np.ndarray) -> list[Segment]:
        """喂入 int16 PCM, 返回本次产生的已完成语音段列表."""
        out: list[Segment] = []
        if pcm is None or pcm.size == 0:
            return out
        self._buf = np.concatenate([self._buf, pcm.astype(np.int16)])

        while self._buf.size >= self.frame_size:
            frame = self._buf[:self.frame_size]
            self._buf = self._buf[self.frame_size:]
            self._process_frame(frame, out)
        return out

    def flush(self) -> list[Segment]:
        """流结束时调用, 提交尚未关闭的语音段."""
        out: list[Segment] = []
        if self._in_speech and len(self._seg_frames) >= self.min_frames:
            self._emit(out)
        self._reset_segment()
        return out

    def _process_frame(self, frame: np.ndarray, out: list[Segment]):
        rms = float(np.sqrt(np.mean(frame.astype(np.float64) ** 2)))
        voiced = rms >= self.rms_threshold
        cur_ms = self._total_frames * self.frame_ms

        if voiced:
            if not self._in_speech:
                self._in_speech = True
                self._seg_begin_ms = cur_ms
                self._seg_frames = []
                self._silence_run = 0
            self._seg_frames.append(frame)
            self._silence_run = 0
            if len(self._seg_frames) >= self.max_frames:
                self._emit(out)
                self._reset_segment()
        else:
            if self._in_speech:
                # keep trailing silence inside the segment until hangover hit
                self._seg_frames.append(frame)
                self._silence_run += 1
                if self._silence_run >= self.hangover_frames:
                    # drop the trailing silence frames before emitting
                    if len(self._seg_frames) - self._silence_run >= self.min_frames:
                        self._seg_frames = self._seg_frames[:-self._silence_run]
                        self._emit(out)
                    self._reset_segment()

        self._total_frames += 1

    def _emit(self, out: list[Segment]):
        pcm = np.concatenate(self._seg_frames) if self._seg_frames else np.zeros(0, dtype=np.int16)
        end_ms = self._seg_begin_ms + int(pcm.size * 1000 / self.rate)
        out.append(Segment(pcm=pcm, begin_ms=self._seg_begin_ms, end_ms=end_ms))

    def _reset_segment(self):
        self._in_speech = False
        self._seg_frames = []
        self._silence_run = 0
