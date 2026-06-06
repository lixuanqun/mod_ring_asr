# 场景:用 ESL 获取检测结果

`esl_listener.py` 无第三方依赖,用原生 socket 实现 ESL inbound:认证后订阅
`CUSTOM tonedetect`(实时)与 `CHANNEL_HANGUP_COMPLETE`(最终结果变量),
解析并打印关注字段。

```bash
# 连接真实 FreeSWITCH ESL
python esl_listener.py --host 127.0.0.1 --port 8021 --password ClueCon

# 不连 FS,演示事件解析(可在本机直接运行)
python esl_listener.py --selftest
```

读取的字段:
- 信号音:`tonedetect_tone` / `tonedetect_finish_cause` / `tonedetect_begin_ms` / `tonedetect_end_ms`
- 号码状态:`tonedetect_da_tone` / `tonedetect_da_category` / `tonedetect_da_alias` / `tonedetect_da_accuracy`

事件值为 URL 编码,示例已用 `urllib.parse.unquote` 解码(中文类别可正常显示)。
