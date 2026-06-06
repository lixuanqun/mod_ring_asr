# mod_tonedetect ↔ 识别服务 WebSocket 协议 (v1)

实时流式长连接,每条 call leg 一条 WebSocket。音频上行用**二进制帧**,控制/结果用**文本帧(JSON)**。

## 连接

- URL: `ws://host:port/` (内网) 或 `wss://host:port/` (公网)
- 子协议: 无要求

## 1. START (client → server, 文本/JSON)

连接后客户端发送的第一条消息,声明媒体参数并鉴权。

```json
{
  "type": "start",
  "version": 1,
  "uuid": "<freeswitch-channel-uuid>",
  "codec": "L16",
  "samplerate": 8000,
  "key": "<auth-key>",
  "params": { "stoptone": "busy silence", "maxdetecttime": 60 }
}
```

服务端校验 `key`,成功回 `ready`,失败回 `error` 并关闭。

```json
{ "type": "ready" }
{ "type": "error", "reason": "bad_key" }
```

## 2. AUDIO (client → server, 二进制)

START 之后的所有二进制帧均为**原始小端 16-bit PCM**(单声道,采样率同 START)。建议 20ms 一帧。

## 3. RESULT (server → client, 文本/JSON)

服务端做 VAD 切片,每识别出一个语音段就推送一条结果(可多次)。

```json
{
  "type": "result",
  "tone": "sample",
  "category": "空号",
  "alias": "does not exist",
  "name": "konghao_yidong",
  "accuracy": "ACCURACY",
  "score": 0.93,
  "point_begin": 1200,
  "point_end": 2600
}
```

- `tone`: `sample`(命中样本库) | `prompt`(有语音但未命中) | `silence`
- `accuracy`: `ACCURACY` | `INACCURACY` | `LOOSE` —— 仅 `ACCURACY` 应触发挂机/上报
- `point_begin`/`point_end`: 语音段在流中的毫秒位置
- `score`: 与最佳样本的相似度 (0..1)

## 4. STOP / FIN

客户端可发 `{"type":"stop"}` 主动结束;服务端在连接关闭前可发 `{"type":"fin"}`。

## 备注

- 低延迟: `TCP_NODELAY`、逐帧发送;VAD 停顿 ~200ms 即提交识别。
- 音频坚持 L16 原始 PCM,不使用有损编码(避免损伤指纹/频率特征)。
- 并发超限服务端回 `{"type":"error","reason":"limit"}`。
