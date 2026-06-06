# mod_tonedetect — FreeSWITCH 回铃音/号码状态检测

通过分析早期媒体(early media)的声音,检测呼叫接续过程中的信号音类型,用于自动外呼系统快速判断呼叫结果(回铃/忙音/拥塞等),无需等待对端 60s 超时挂断。

对标顶顶通 `mod_da2` 的能力,分阶段自研实现:

- **阶段 1(本仓库当前内容)**:FreeSWITCH 模块 + 本地 DSP,识别**国内 450Hz 体系**的信号音:回铃音、忙音、拥塞音、450hz 嘟音、静音,以及"非纯音(other,疑似彩铃/语音)"的粗分。
- **阶段 2(规划)**:独立识别服务 + 音频指纹/样本库匹配(经 WebSocket/libwebsockets 流式对接),识别空号/关机/停机/语音信箱等语音提示音。
- **阶段 3(规划)**:ASR 兜底 + 样本回流。

## 目录结构

| 路径 | 说明 |
|---|---|
| `src/tone_dsp.{h,c}` | 与 FreeSWITCH 解耦的 DSP 核心:Goertzel 单频检测 + cadence 节奏状态机 |
| `module/mod_tonedetect.c` | FreeSWITCH 模块:media bug 抓早期媒体 → DSP → channel 变量 / CUSTOM 事件 / autohangup |
| `module/tonedetect.conf.xml` | 模块配置(stoptone / autohangup / maxdetecttime / 节奏规则) |
| `module/Makefile` | 针对已安装的 FreeSWITCH 构建 `mod_tonedetect.so` |
| `test/` | 离线测试:WAV 读写、合成音生成器、检测器测试程序 |
| `Makefile` | 离线构建并运行 DSP 检测测试(无需 FreeSWITCH) |

## 离线测试 DSP 核心(无需 FreeSWITCH)

```bash
make test
```

会生成合成的回铃/忙音/拥塞/静音/other/级联场景 WAV,并断言检测器输出正确。

## 构建并安装 FreeSWITCH 模块

需要已安装 FreeSWITCH 及其开发头文件(`libfreeswitch-dev` 或源码)。

```bash
cd module
make FS_INCLUDE=/usr/include/freeswitch FS_MODDIR=/usr/lib/freeswitch/mod
sudo make install
```

在 `modules.conf.xml` 中加载 `mod_tonedetect`。

## 使用

收到 183 早期媒体时启动检测:

```
originate {ignore_early_media=consume,execute_on_pre_answer=start_tonedetect}sofia/gateway/NUMBER &park
```

### 结果(channel 变量)

- `tonedetect_tone`:最近/最佳信号音类型(`ringback`/`busy`/`congestion`/`450hz`/`silence`/`other`)
- `tonedetect_finish_cause`:停止原因(`stoptone`/`timeout`/`stop`)

### CUSTOM 事件

订阅 `Event-Subclass: tonedetect`,头部含 `tonedetect_tone`、`tonedetect_begin_ms`、`tonedetect_end_ms`。

### 每通可覆盖的 channel 变量

- `tonedetect_stoptone`:命中即停止的信号音列表,如 `busy silence`(可选 `all`)
- `tonedetect_autohangup`:`true`/`false`,命中 stoptone 是否自动挂机
- `tonedetect_maxdetecttime`:最大检测秒数

## 国内 450Hz 节奏标准(默认)

| 信号音 | ON | OFF |
|---|---|---|
| 回铃音 ringback | ~1000ms | ~4000ms |
| 忙音 busy | ~350ms | ~350ms |
| 拥塞/快忙 congestion | ~700ms | ~700ms |

节奏容差与阈值可在 `tonedetect.conf.xml` 调整。
