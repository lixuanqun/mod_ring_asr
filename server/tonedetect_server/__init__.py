"""tonedetect_server -- WebSocket 回铃音/号码状态识别服务 (阶段2).

接收 FreeSWITCH mod_tonedetect 经 WebSocket 推送的早期媒体 L16 音频,
做 VAD 切片 + 音频指纹/样本库匹配,返回号码状态识别结果。
"""

__version__ = "0.1.0"
