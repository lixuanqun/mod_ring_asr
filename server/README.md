# tonedetect 识别服务 (阶段2)

接收 FreeSWITCH `mod_tonedetect` 经 WebSocket 推送的早期媒体 L16 音频,做
**VAD 切片 + 音频指纹/样本库匹配**,识别号码状态(空号/关机/停机/语音信箱等
语音提示音),并回推识别结果。协议与对接见 [`../docs/INTEGRATION.md`](../docs/INTEGRATION.md)。

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

## 样本库采集流程(闭环)

准确率取决于样本库覆盖度。系统提供"自动回流 → 人工打标 → 入库 → 即刻命中"的闭环:

```
                  ┌─────────────────────────────────────────────┐
                  │  未命中(prompt)的语音段                       │
  早期媒体 ──►识别─┤                                              │
                  │  命中(sample)→ 直接返回结果                   │
                  └──────────────┬──────────────────────────────┘
                                 │ --capture-dir 自动落盘 WAV+sidecar
                                 ▼
                          待标注目录 (capture/)
                                 │ sampletool promote(人工打标)
                                 ▼
                          样本库 (samples/) ──► 重载后即可命中
```

**采集来源**

1. **服务端自动回流**:服务以 `--capture-dir ./capture` 启动后,所有未命中(`prompt`)的
   语音段会自动存成 `<uuid>_<ts>_<begin>.wav` + 同名 `.json`(含 uuid/score/时间)。
2. **mod 侧录音**:`tonedetect.conf.xml` 配 `recordpath`(或通道变量 `tonedetect_record_path`),
   把整段早期媒体录成 `<uuid>.wav`,供人工裁剪入库。

**打标入库 CLI(`sampletool`)**

```bash
# 查看待标注的回流录音
python -m tonedetect_server.sampletool pending --capture ./capture

# 试听后, 把某条回流录音打标正式入库(自动转 8k 单声道, 并清理回流文件)
python -m tonedetect_server.sampletool promote --samples ./samples \
       --wav ./capture/uuidX_1.wav --name konghao_yidong --alias "does not exist" --category 空号

# 直接入库一个已有 WAV
python -m tonedetect_server.sampletool add --samples ./samples \
       --wav prompt.wav --name guanji_yidong --alias "power off" --category 关机

python -m tonedetect_server.sampletool list   --samples ./samples   # 列出
python -m tonedetect_server.sampletool remove --samples ./samples --name guanji_yidong
```

入库后重启服务(或重新加载样本库)即可命中该提示音。

## 阶段3: ASR 兜底 + 自动回流补库

样本库未命中(`prompt`)的段,可经 **ASR 转写 + 关键词归类** 兜底识别号码状态
(覆盖样本库尚未收录的措辞/运营商差异),并可**自动把该段补进样本库并热重载**,
使下次走更快更准的指纹匹配。

```
指纹未命中(prompt)
   └─ASR 兜底─► 转写文本 ─关键词归类─► 命中? ──是──► 返回 tone=asr + 号码状态
                                          │           └─(--asr-autolearn)自动补库+热重载
                                          └─否──► 仍 prompt(落 capture 待人工)
```

启用(需先实现/接入真实 ASR 引擎):

```bash
python -m tonedetect_server --samples ./samples --asr whisper --asr-autolearn
```

- ASR 引擎**可插拔**:在 `asr.create_asr()` 里接入本地 Whisper 或云端 ASR
  (`StubASR` 仅用于测试/演示)。
- `KeywordClassifier`(`asr.py`)把转写文本按关键词映射为号码状态(关机/空号/停机/
  通话中/语音信箱/暂停服务…),规则可扩展。
- 返回结果 `tone="asr"`,带 `category`/`alias`/`text`。

## 测试

```bash
. .venv/bin/activate
python tests/test_matcher.py          # 指纹匹配 + VAD 单测(无网络)
python tests/test_ws_e2e.py           # WebSocket 端到端(进程内起服务 + 客户端)
python tests/test_library_admin.py    # 样本库 add/list/remove/promote + 重采样
python tests/test_capture_reflow.py   # 闭环: 未命中回流 -> 打标入库 -> 命中
python tests/test_asr.py              # ASR 关键词分类器 + 兜底
python tests/test_asr_reflow.py       # 闭环: 未命中 -> ASR归类 -> 自动补库 -> 指纹命中
```
