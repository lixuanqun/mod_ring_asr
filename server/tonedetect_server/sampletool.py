"""样本库管理 CLI.

  # 列出样本
  python -m tonedetect_server.sampletool list   --samples ./samples

  # 入库一个 WAV (自动转 8k 单声道)
  python -m tonedetect_server.sampletool add    --samples ./samples \
         --wav prompt.wav --name konghao_yidong --alias "does not exist" --category 空号

  # 删除样本
  python -m tonedetect_server.sampletool remove --samples ./samples --name konghao_yidong

  # 把回流目录里未命中的录音正式入库(打标)
  python -m tonedetect_server.sampletool promote --samples ./samples \
         --wav ./capture/uuid_123.wav --name guanji_yidong --alias "power off" --category 关机

  # 列出待标注的回流录音
  python -m tonedetect_server.sampletool pending --capture ./capture
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import library, states


def _cmd_states(args):
    print(f"{'id':>3} {'name':10} {'alias':22} description")
    for s in states.STATES:
        print(f"{s.id:>3} {s.name:10} {s.alias:22} {s.description}")
    print("\n信号音: " + ", ".join(f"{k}({v})" for k, v in states.SIGNAL_TONES.items()))
    return 0


def _cmd_list(args):
    entries = library.list_samples(args.samples)
    if not entries:
        print("(empty)")
        return 0
    print(f"{'name':24} {'alias':22} {'category':10} file")
    for e in entries:
        print(f"{e.get('name',''):24} {e.get('alias',''):22} {e.get('category',''):10} {e.get('file','')}")
    print(f"total: {len(entries)}")
    return 0


def _cmd_add(args):
    e = library.add_sample(args.samples, args.wav, args.name, args.alias or "", args.category or "")
    print(f"added: {e}")
    return 0


def _cmd_remove(args):
    ok = library.remove_sample(args.samples, args.name)
    print("removed" if ok else "not found")
    return 0 if ok else 1


def _cmd_promote(args):
    e = library.promote(args.samples, args.wav, args.name, args.alias or "", args.category or "")
    print(f"promoted into library: {e}")
    return 0


def _cmd_pending(args):
    if not os.path.isdir(args.capture):
        print("(no capture dir)")
        return 0
    wavs = sorted(f for f in os.listdir(args.capture) if f.endswith(".wav"))
    if not wavs:
        print("(none)")
        return 0
    for w in wavs:
        meta = os.path.join(args.capture, os.path.splitext(w)[0] + ".json")
        info = ""
        if os.path.isfile(meta):
            with open(meta, "r", encoding="utf-8") as f:
                info = json.dumps(json.load(f), ensure_ascii=False)
        print(f"{w}  {info}")
    print(f"total pending: {len(wavs)}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="sampletool", description="tonedetect sample-library管理")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("states").set_defaults(fn=_cmd_states)

    p = sub.add_parser("list"); p.add_argument("--samples", required=True); p.set_defaults(fn=_cmd_list)

    p = sub.add_parser("add")
    p.add_argument("--samples", required=True); p.add_argument("--wav", required=True)
    p.add_argument("--name", required=True); p.add_argument("--alias"); p.add_argument("--category")
    p.set_defaults(fn=_cmd_add)

    p = sub.add_parser("remove")
    p.add_argument("--samples", required=True); p.add_argument("--name", required=True)
    p.set_defaults(fn=_cmd_remove)

    p = sub.add_parser("promote")
    p.add_argument("--samples", required=True); p.add_argument("--wav", required=True)
    p.add_argument("--name", required=True); p.add_argument("--alias"); p.add_argument("--category")
    p.set_defaults(fn=_cmd_promote)

    p = sub.add_parser("pending"); p.add_argument("--capture", required=True); p.set_defaults(fn=_cmd_pending)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
