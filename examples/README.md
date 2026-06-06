# 示例(examples)

按场景给出可运行的示例代码与说明。完整协议/对接细节见 [`../docs/INTEGRATION.md`](../docs/INTEGRATION.md)。

| 目录 | 场景 | 关键文件 | 可本地运行 |
|---|---|---|---|
| [`freeswitch/`](./freeswitch) | 在 FreeSWITCH 启动检测(dialplan / originate) | `dialplan_tonedetect.xml`、`originate_examples.sh` | 需 FreeSWITCH |
| [`ws_client/`](./ws_client) | 把 WAV 推给识别服务(模拟 mod 客户端) | `stream_wav.py` | ✅(需识别服务) |
| [`custom_server/`](./custom_server) | 自建兼容识别服务(第三方最小实现) | `minimal_recognition_server.py` | ✅ |
| [`esl/`](./esl) | 用 ESL 实时获取检测结果 | `esl_listener.py` | ✅(`--selftest`)/ 需 FreeSWITCH |
| [`sample_library/`](./sample_library) | 样本库采集与入库流程 | `build_library.sh` | ✅(需识别服务依赖) |

## 快速串起来(纯本地,不需要 FreeSWITCH)

用"自建最小服务 + WS 推流客户端"演示端到端链路:

```bash
pip install websockets

# 终端 A:启动一个最小兼容识别服务
python examples/custom_server/minimal_recognition_server.py --port 9977

# 终端 B:把任意 8k/16bit 单声道 WAV 推过去,看返回 RESULT
python examples/ws_client/stream_wav.py --url ws://127.0.0.1:9977/ --wav your.wav
```

要用功能完整的识别服务(VAD + 音频指纹 + 样本库 + ASR 兜底),把终端 A 换成:

```bash
cd server && python -m tonedetect_server --samples ./samples --port 9977
```

## 真实部署链路

```
FreeSWITCH(mod_tonedetect)
  ├─ 本地 DSP ──► 信号音(回铃/忙音/拥塞...)──► channel 变量 + CUSTOM 事件 ──► ESL(esl_listener.py)
  └─ ws_client ──► 识别服务(custom_server 或 server/)──► 号码状态 ──► channel 变量/事件
```

- 在 FreeSWITCH 侧用 `freeswitch/` 的 dialplan/originate 启动检测;
- 用 `esl/esl_listener.py` 订阅结果;
- 识别服务可用本仓库 `server/`,或参考 `custom_server/` 自建。
