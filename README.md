# mod_tonedetect — FreeSWITCH 回铃音/号码状态检测

通过分析早期媒体(early media)的声音,检测呼叫接续过程中的信号音类型与被叫号码状态,用于自动外呼系统快速判断呼叫结果(回铃/忙音/拥塞/空号/关机等),无需等待对端 60s 超时挂断,从而节省线路资源、提高外呼速度与坐席接通率。

能力对标顶顶通 `mod_da2`,采用**本地 mod + 独立识别服务**的分层架构,分阶段自研实现。

---

## 一、技术方案

### 1.1 整体架构

```
                     早期媒体(183) PCM
  ┌──────────────┐   ───────────────────►   ┌─────────────────────────┐
  │  FreeSWITCH   │     WebSocket(L16)        │   独立识别服务            │
  │  mod_tonedetect│  ◄───────────────────    │  (阶段2/3, 进程外)        │
  │  + 本地 DSP    │     JSON 识别结果          │  VAD + 音频指纹 + ASR     │
  └──────────────┘                           └─────────────────────────┘
        │
        ├─ 信号音(回铃/忙音/拥塞/450hz/静音) → 本地 DSP 直接判定(阶段1)
        └─ 语音提示音(空号/关机/停机/语音信箱) → 转发识别服务(阶段2/3)
```

设计原则:**FreeSWITCH 模块只做"媒体采集 + 结果回填 + 挂机控制",重计算放进程外的识别服务**,便于独立扩缩容、算法迭代与私有化部署。

### 1.2 分阶段路线

| 阶段 | 范围 | 识别手段 | 状态 |
|---|---|---|---|
| **阶段 1** | 国内 450Hz 信号音:回铃/忙音/拥塞/450hz/静音 + other(疑似彩铃/语音粗分) | 本地 DSP(Goertzel + cadence) | ✅ 已实现 |
| **阶段 2** | 语音提示音:空号/关机/停机/通话中/语音信箱等 | 独立 Python 服务([`server/`](./server)) + VAD 切片 + **音频指纹/样本库匹配** | ✅ 已实现 |
| **阶段 3** | 样本库未命中的兜底与泛化 | **ASR 转写 + 关键词匹配**,ASR 归类的段自动回流补库(热重载) | ✅ 已实现 |

> 选型依据:语音提示音识别以**音频指纹/样本库匹配**为主(快、省 CPU、加样本即扩展),ASR 仅作兜底。彩铃/真人等"非纯音"先由 DSP 粗分为 `other`,交识别服务细分。

### 1.3 阶段 1 — 信号音 DSP 算法

与 FreeSWITCH 解耦,实现于 `src/tone_dsp.{h,c}`,可离线单测。

**处理流水线**

```
PCM 16bit mono → 20ms 分析块 → 每块标签{TONE_450 | SILENCE | OTHER} → cadence 状态机 → 信号音分类
```

1. **分块**:按 `block_ms`(默认 20ms = 8k 下 160 样本)切块。
2. **Goertzel 单频检测**:在 450Hz 对应 DFT bin 上算能量,得到"纯音占比"`purity = 2*goertzel_power / (N*energy)`(纯音≈1,语音/噪声偏小);结合 RMS 静音门限,给每块打标签:
   - `SILENCE`:RMS < `silence_rms`
   - `TONE`:`purity ≥ purity_threshold`(450Hz 主导)
   - `OTHER`:有能量但非 450 主导(彩铃/语音候选)
3. **cadence 节奏状态机**:跟踪 ON(TONE)/OFF(SILENCE)段的时长,按规则匹配:
   - 命中级联结果(busy/congestion/ringback)后"粘性"保持,不被裸 450hz 降级
   - 回铃 OFF 长达 ~4s,silence 超过 `ring_early_off_ms`(默认 2s)即**提前判定回铃**,加快速度
   - 持续 OTHER ≥ `min_other_ms` 上报 `other`;静默起始持续 ≥ `silence_min_ms` 上报 `silence`

**国内 450Hz 节奏标准(默认,可配置容差)**

| 信号音 | ON | OFF |
|---|---|---|
| 回铃音 ringback | ~1000ms | ~4000ms |
| 忙音 busy | ~350ms | ~350ms |
| 拥塞/快忙 congestion | ~700ms | ~700ms |

### 1.4 阶段 2/3 — mod ↔ 识别服务 WebSocket 协议(设计)

链路为**实时流式长连接**:8kHz/16bit/单声道、20ms 帧(320 字节),双向(上行音频、下行多次结果),要求低延迟、高并发、可鉴权、可断线重连。客户端用 **libwebsockets**(纯 C,契合 FS 模块,参考 `mod_audio_fork`)。

**连接与编码**

- 每条 call leg 一条 WebSocket 流;长连接 + 心跳 + 断线重连。
- 音频:**L16 / 8kHz / 单声道原始 PCM**,二进制帧(不用有损编码,避免损伤频率特征/指纹)。
- `TCP_NODELAY` 关 Nagle、逐帧 flush;VAD 切片(停顿 ~200ms 提交)在服务端做。
- 内网私有化走 `ws://`;公网走 `wss://`。

**消息类型(三类)**

| 方向 | 帧 | 内容 |
|---|---|---|
| mod → 服务 | `START`(文本/JSON) | `version`、`uuid`、`codec`、`samplerate`、`key`(鉴权)、检测参数 |
| mod → 服务 | `AUDIO`(二进制) | 连续 L16 PCM 帧 |
| 服务 → mod | `RESULT`/`EVENT`(文本/JSON) | `point_begin/point_end`、`tone`、命中样本 `uniqueid/name/alias/category`、`accuracy`,以及 `STOP/FIN` |

**握手示例(START)**

```json
{ "type": "start", "version": 1, "uuid": "<channel-uuid>",
  "codec": "L16", "samplerate": 8000, "key": "<auth-key>",
  "params": { "stoptone": "busy silence", "maxdetecttime": 60 } }
```

**结果示例(RESULT)**

```json
{ "type": "result", "tone": "does_not_exist", "category": "空号",
  "accuracy": "ACCURACY", "point_begin": 1200, "point_end": 2600,
  "sample": { "uniqueid": "...", "name": "...", "alias": "does not exist" } }
```

只有 `accuracy = ACCURACY` 的结果才通知 ESL / 触发挂机。背压/并发超限时服务端回 `limit`,mod 优雅降级。

---

## 二、对接方式

### 2.1 启动检测

收到 183 早期媒体时启动(`execute_on_pre_answer`);模拟线路无 183 直接应答的,用 `execute_on_media`。

**originate**

```
originate {ignore_early_media=consume,execute_on_pre_answer=start_tonedetect}sofia/gateway/NUMBER &park
```

- `ignore_early_media=consume`:若原拨号串用 `ignore_early_media=true` 需改为 `consume`,否则收不到/不消费早期媒体。
- 若 FS 无公网 IP / RTP 端口未映射,需先发媒体流才能收到早期媒体,可加
  `execute_on_pre_answer_sendrtp=playback::silence_stream://1000`。

**dialplan**

```xml
<extension name="tonedetect">
  <condition field="destination_number" expression="^(\d+)$">
    <action application="export" data="nolocal:execute_on_pre_answer=start_tonedetect"/>
    <action application="bridge" data="sofia/gateway/${1}"/>
  </condition>
</extension>
```

停止检测(一般电话接通/挂断会自动停止,也可手动):`stop_tonedetect`。

### 2.2 每通可覆盖的 channel 变量(呼叫前 set/export)

| 变量 | 说明 |
|---|---|
| `tonedetect_stoptone` | 命中即停止的信号音列表:`busy ringback congestion 450hz silence other`(或 `all`) |
| `tonedetect_autohangup` | `true`/`false`,命中 stoptone 是否自动挂机 |
| `tonedetect_maxdetecttime` | 最大检测秒数 |

### 2.3 获取结果 —— channel 变量

检测过程会持续更新以下变量,在 `CHANNEL_HANGUP_COMPLETE` 等事件里读取(ESL 中前缀 `variable_`):

| 变量 | 说明 |
|---|---|
| `tonedetect_tone` | 最近/最佳信号音类型:`ringback`/`busy`/`congestion`/`450hz`/`silence`/`other` |
| `tonedetect_finish_cause` | 停止原因:`stoptone`(命中停止音)/`timeout`(超时)/`stop`(手动/通话结束) |

### 2.4 获取结果 —— CUSTOM 事件(实时)

订阅 `Event-Subclass: tonedetect`(`Event-Name: CUSTOM`):

```
/event CUSTOM tonedetect          # fs_cli
```

事件头部:

| 头 | 说明 |
|---|---|
| `tonedetect_tone` | 信号音类型 |
| `tonedetect_begin_ms` | 证据起始(流相对毫秒) |
| `tonedetect_end_ms` | 证据结束(流相对毫秒) |

ESL 订阅示例:`CHANNEL_HANGUP_COMPLETE CUSTOM tonedetect`。

### 2.5 SIP 挂机码反馈(规划,阶段2)

参考 `mod_da2`,可把识别到的号码状态映射为自定义 SIP 挂断码(如 空号→433、关机→432、停机→434…),让上游外呼系统通过挂机码即可获知结果,实现 `VOS → 检测系统 → VOS` 的纯 SIP 对接,无需二次开发。该映射将在阶段 2 随识别服务一并提供。

---

## 三、目录结构

| 路径 | 说明 |
|---|---|
| `src/tone_dsp.{h,c}` | 与 FreeSWITCH 解耦的 DSP 核心:Goertzel + cadence 状态机 |
| `src/ws_client.{h,c}` | 与 FreeSWITCH 解耦的 libwebsockets 客户端:把 L16 音频流式推给识别服务 |
| `server/` | 阶段2 独立 Python 识别服务(WebSocket + VAD + 音频指纹/样本库匹配),见 `server/README.md` |
| `module/mod_tonedetect.c` | FreeSWITCH 模块:media bug 抓早期媒体 → 本地 DSP + 经 WebSocket 推流识别服务 → channel 变量 / CUSTOM 事件 / autohangup |
| `module/tonedetect.conf.xml` | 模块配置(stoptone / autohangup / maxdetecttime / 节奏规则) |
| `module/Makefile` | 针对已安装的 FreeSWITCH 构建 `mod_tonedetect.so` |
| `test/` | 离线测试:WAV 读写、合成音生成器、检测器测试程序 |
| `Makefile` | 离线构建并运行 DSP 检测测试(无需 FreeSWITCH) |

---

## 四、构建与测试

### 4.1 离线测试 DSP 核心(无需 FreeSWITCH)

```bash
make test
```

生成合成的 回铃/忙音/拥塞/静音/other/级联 场景 WAV,并断言检测器输出正确。

### 4.2 构建并安装 FreeSWITCH 模块

需已安装 FreeSWITCH 及其开发头文件(`libfreeswitch-dev` 或源码)。

```bash
cd module
make FS_INCLUDE=/usr/include/freeswitch FS_MODDIR=/usr/lib/freeswitch/mod
sudo make install
```

将 `tonedetect.conf.xml` 放入 `autoload_configs/`,并在 `modules.conf.xml` 中加载 `mod_tonedetect`。

### 4.3 配置项(`tonedetect.conf.xml`)

| 参数 | 说明 |
|---|---|
| `stoptone` | 命中即停止的信号音(可被 `tonedetect_stoptone` 覆盖) |
| `autohangup` | 命中 stoptone 是否自动挂机(可被 `tonedetect_autohangup` 覆盖) |
| `maxdetecttime` | 最大检测秒数(可被 `tonedetect_maxdetecttime` 覆盖) |
| `purity_threshold` | 450Hz 纯音占比阈值(0..1) |
| `silence_rms` | 静音 RMS 门限(满量程 32768) |
| `tone_busy_rule` / `tone_congestion_rule` / `tone_ringback_rule` | 节奏规则 `on_min-on_max\|off_min-off_max`(毫秒) |
