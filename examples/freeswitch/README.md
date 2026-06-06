# 场景:在 FreeSWITCH 启动检测

前置:已编译安装并加载 `mod_tonedetect`(见仓库根 `README.md` 与 `module/`)。

- `dialplan_tonedetect.xml`:4 种 dialplan 用法(最简、命中即挂机、录音采集、`execute_on_media`)。把需要的 `<extension>` 放进你的 dialplan。
- `originate_examples.sh`:`fs_cli originate` 命令模板,`bash originate_examples.sh` 打印命令(替换 `GW`/`NUMBER`)。

要点:
- 收到 183 早期媒体用 `execute_on_pre_answer=start_tonedetect`;无 183 用 `execute_on_media`。
- 原拨号串若有 `ignore_early_media=true`,改成 `ignore_early_media=consume`。
- 每通可用 `tonedetect_stoptone` / `tonedetect_autohangup` / `tonedetect_maxdetecttime` / `tonedetect_record_path` 覆盖。
- 结果读取见 [`../esl`](../esl) 与 [`../../docs/INTEGRATION.md`](../../docs/INTEGRATION.md) 第 5 节。
