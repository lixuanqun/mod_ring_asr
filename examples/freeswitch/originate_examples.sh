#!/usr/bin/env bash
# 示例:用 fs_cli / fs_cli -x 通过 originate 发起带检测的外呼。
# 这些是命令模板,按你的网关与号码替换 mygw / NUMBER。
set -euo pipefail

GW="${GW:-mygw}"
NUMBER="${NUMBER:-10086}"

echo "# 1) 最简单:收到 183 即检测,呼叫 park 在 a-leg"
echo "fs_cli -x \"originate {ignore_early_media=consume,execute_on_pre_answer=start_tonedetect}sofia/gateway/${GW}/${NUMBER} &park\""

echo
echo "# 2) 命中忙音/静音自动挂机 + 限制最大检测 45s"
echo "fs_cli -x \"originate {ignore_early_media=consume,tonedetect_stoptone='busy congestion silence',tonedetect_autohangup=true,tonedetect_maxdetecttime=45,execute_on_pre_answer=start_tonedetect}sofia/gateway/${GW}/${NUMBER} &park\""

echo
echo "# 3) FS 无公网IP / RTP未映射:先发媒体流才能收到早期媒体"
echo "fs_cli -x \"originate {ignore_early_media=consume,execute_on_pre_answer_sendrtp=playback::silence_stream://1000,execute_on_pre_answer_td=start_tonedetect}sofia/gateway/${GW}/${NUMBER} &park\""

echo
echo "# 4) 检测后转入 dialplan 继续业务(应答后)"
echo "fs_cli -x \"originate {execute_on_pre_answer=start_tonedetect}sofia/gateway/${GW}/${NUMBER} &transfer:'1000 XML default'\""

echo
echo "# 读取结果:订阅事件"
echo "fs_cli -x \"...\"; 然后在另一个 fs_cli 里: /event plain CUSTOM tonedetect CHANNEL_HANGUP_COMPLETE"
