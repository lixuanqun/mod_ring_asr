#!/usr/bin/env bash
# 示例:用 sampletool 构建与维护样本库,并演示"未命中回流 -> 打标入库"。
# 需先安装识别服务依赖(见 server/README.md)。
set -euo pipefail

# 仓库根目录(本脚本在 examples/sample_library/ 下)
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SERVER="$ROOT/server"
SAMPLES="${SAMPLES:-/tmp/td_samples}"
CAPTURE="${CAPTURE:-/tmp/td_capture}"

export PYTHONPATH="$SERVER"
PY="${PY:-python3}"

echo "# 1) 直接入库一个已有 WAV(自动转 8k 单声道)"
echo "$PY -m tonedetect_server.sampletool add --samples $SAMPLES \\"
echo "      --wav /path/to/guanji.wav --name guanji_yidong --alias 'power off' --category 关机"
echo

echo "# 2) 启动识别服务并开启未命中回流(另一个终端)"
echo "$PY -m tonedetect_server --samples $SAMPLES --capture-dir $CAPTURE"
echo

echo "# 3) 查看回流目录里待标注的录音"
echo "$PY -m tonedetect_server.sampletool pending --capture $CAPTURE"
echo

echo "# 4) 试听后把某条回流录音打标正式入库(并清理回流文件)"
echo "$PY -m tonedetect_server.sampletool promote --samples $SAMPLES \\"
echo "      --wav $CAPTURE/<uuid>.wav --name konghao_yidong --alias 'does not exist' --category 空号"
echo

echo "# 5) 查看 / 删除样本"
echo "$PY -m tonedetect_server.sampletool list   --samples $SAMPLES"
echo "$PY -m tonedetect_server.sampletool remove --samples $SAMPLES --name guanji_yidong"
echo
echo "# 入库后重启服务(或热重载)即可命中。"
