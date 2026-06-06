# 场景:自建兼容识别服务(第三方)

`minimal_recognition_server.py` 是一个**最小但合规**的识别服务,演示如何按
[`docs/INTEGRATION.md`](../../docs/INTEGRATION.md) 的契约对接 `mod_tonedetect`:

握手 `START`→`ready` → 收二进制 L16 → 简单能量 VAD 切段 → 每段回 `RESULT` → `stop`→`fin`。

```bash
pip install websockets
python minimal_recognition_server.py --host 0.0.0.0 --port 9977 --key ""
# 另开终端:
python ../ws_client/stream_wav.py --url ws://127.0.0.1:9977/ --wav some.wav
```

把你的识别引擎(音频指纹 / ASR / 已有系统)接到 `classify_segment()` 即可。
命中时返回 `{"tone":"sample","category":"空号","alias":"does not exist","accuracy":"ACCURACY"}`,
**仅 `accuracy=ACCURACY`** 会触发 mod 上报/挂机。

> 功能完整的参考实现见仓库 `server/`(VAD + 音频指纹 + 样本库 + ASR 兜底)。
