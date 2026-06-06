# tonedetect 识别服务 (阶段2)

接收 FreeSWITCH `mod_tonedetect` 经 WebSocket 推送的早期媒体 L16 音频,做
**VAD 切片 + 音频指纹/样本库匹配**,识别号码状态(空号/关机/停机/语音信箱等
语音提示音),并回推识别结果。协议见 [`PROTOCOL.md`](./PROTOCOL.md)。

## 安装

```bash
cd server
python3 -m venv --system-site-packages .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## 运行

```bash
python -m tonedetect_server --host 0.0.0.0 --port 9977 --samples ./samples --key mykey
```

- `--samples`:样本库目录,内含若干参考提示音 WAV 与 `samples.json`
- `--key`:鉴权 key(与 mod 的 `server_key` 一致;留空则不校验)
- `--accuracy` / `--inaccuracy`:相似度分级阈值(默认 0.75 / 0.60)

对应在 `tonedetect.conf.xml` 配置 mod 侧:

```xml
<param name="server_url" value="ws://127.0.0.1:9977/"/>
<param name="server_key" value="mykey"/>
```

## 样本库格式

`samples/samples.json`:

```json
[
  {"file": "konghao.wav", "name": "konghao_yidong",
   "alias": "does not exist", "category": "空号"}
]
```

每个 `file` 为 8kHz/16bit 单声道 WAV。加载时预计算指纹;查询段与样本库做
余弦相似度匹配,`>= accuracy` 判为命中(`ACCURACY`)。

> **样本库是准确率的关键**:需持续采集各运营商/地区的真实提示音录音入库
> (mod 侧可开录音协助采集)。未命中(`prompt`)的段将在阶段3交 ASR 兜底并回流补库。

## 识别原理

| 步骤 | 模块 | 说明 |
|---|---|---|
| VAD 切片 | `vad.py` | 能量门限分帧,语音后停顿 ~200ms 即提交一个语音段 |
| 音频指纹 | `fingerprint.py` | 电话频带对数频带能量 → 时间平滑 → 逐帧去均值 → 时间轴归一 → L2 归一(增益/轻噪鲁棒) |
| 样本匹配 | `matcher.py` | 与样本库指纹求余弦相似度,最近邻 + 阈值分级 |
| WS 服务 | `server.py` | START 握手/鉴权 → 收 L16 二进制帧 → 切片匹配 → 回 RESULT JSON |

## 测试

```bash
. .venv/bin/activate
python tests/test_matcher.py    # 指纹匹配 + VAD 单测(无网络)
python tests/test_ws_e2e.py     # WebSocket 端到端(进程内起服务 + 客户端)
```
