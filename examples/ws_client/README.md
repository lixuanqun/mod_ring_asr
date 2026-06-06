# 场景:WebSocket 推流客户端

`stream_wav.py` 模拟 `mod_tonedetect` 的客户端:连接识别服务 → 发 `START` → 按 20ms
推二进制 L16 帧 → 打印 `RESULT`。用于联调任何兼容 [协议](../../docs/INTEGRATION.md) 的服务。

```bash
pip install websockets
python stream_wav.py --url ws://127.0.0.1:9977/ --wav prompt.wav --key ""
```

- WAV 需为 16-bit PCM(多声道取声道0);采样率取自文件并在 `START` 中声明。
- 配合 [`../custom_server`](../custom_server) 或 `server/` 使用。
