#!/usr/bin/env python3
"""示例:用 ESL(Event Socket)实时获取 tonedetect 检测结果。

无第三方依赖(原生 socket 实现 ESL inbound)。订阅:
  - CUSTOM / tonedetect   实时信号音与号码状态事件
  - CHANNEL_HANGUP_COMPLETE  挂断时读取最终结果变量

用法:
  python esl_listener.py --host 127.0.0.1 --port 8021 --password ClueCon
  python esl_listener.py --selftest      # 不连 FS,演示事件解析

结果字段(见 docs/INTEGRATION.md):
  tonedetect_tone / tonedetect_finish_cause
  tonedetect_da_tone / tonedetect_da_category / tonedetect_da_alias / tonedetect_da_accuracy
"""
from __future__ import annotations

import argparse
import socket
import sys
from urllib.parse import unquote

INTEREST = ["tonedetect_tone", "tonedetect_finish_cause", "tonedetect_source",
            "tonedetect_da_tone", "tonedetect_da_category", "tonedetect_da_alias",
            "tonedetect_da_accuracy", "tonedetect_begin_ms", "tonedetect_end_ms"]


def parse_event_body(text: str) -> dict:
    """解析 event-plain 正文(Key: value 行,值为 URL 编码)。"""
    out = {}
    for line in text.split("\n"):
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = unquote(v.strip())
    return out


def show(ev: dict):
    name = ev.get("Event-Name", "")
    sub = ev.get("Event-Subclass", "")
    uuid = ev.get("Unique-ID") or ev.get("Channel-Call-UUID", "")
    fields = {}
    for k, val in ev.items():
        base = k[len("variable_"):] if k.startswith("variable_") else k
        if base in INTEREST:
            fields[base] = val
    if not fields:
        return
    tag = f"{name}/{sub}" if sub else name
    print(f"[{tag}] uuid={uuid} " + " ".join(f"{k}={v}" for k, v in fields.items()))


class ESL:
    def __init__(self, host, port, password):
        self.sock = socket.create_connection((host, port), timeout=10)
        self.buf = b""
        self._expect("auth/request")
        self._send(f"auth {password}\n\n")
        self._read_message()  # command/reply
        # 订阅:CUSTOM 的 tonedetect 子类 + 挂断完成
        self._send("event plain CUSTOM tonedetect\n\n")
        self._read_message()
        self._send("event plain CHANNEL_HANGUP_COMPLETE\n\n")
        self._read_message()

    def _send(self, s: str):
        self.sock.sendall(s.encode())

    def _recv_until(self, sep: bytes) -> bytes:
        while sep not in self.buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("ESL closed")
            self.buf += chunk
        idx = self.buf.index(sep) + len(sep)
        head, self.buf = self.buf[:idx], self.buf[idx:]
        return head

    def _expect(self, marker: str):
        head = self._recv_until(b"\n\n").decode(errors="replace")
        if marker not in head:
            raise ConnectionError(f"expected {marker}, got: {head!r}")

    def _read_message(self):
        head = self._recv_until(b"\n\n").decode(errors="replace")
        headers = parse_event_body(head)
        length = int(headers.get("Content-Length", "0") or "0")
        body = b""
        while len(body) < length:
            need = length - len(body)
            if len(self.buf) >= need:
                body, self.buf = self.buf[:need], self.buf[need:]
                break
            body += self.buf
            self.buf = b""
            body += self.sock.recv(4096)
        return headers, body.decode(errors="replace")

    def loop(self):
        print("subscribed; waiting for tonedetect events (Ctrl-C to stop)...")
        while True:
            headers, body = self._read_message()
            ctype = headers.get("Content-Type", "")
            if ctype.startswith("text/event-plain"):
                show(parse_event_body(body))


SAMPLE_EVENT = (
    "Event-Name: CHANNEL_HANGUP_COMPLETE\n"
    "Unique-ID: 1234-abcd\n"
    "variable_tonedetect_tone: busy\n"
    "variable_tonedetect_finish_cause: stoptone\n"
    "variable_tonedetect_da_tone: sample\n"
    "variable_tonedetect_da_category: %E7%A9%BA%E5%8F%B7\n"      # 空号 (URL-encoded)
    "variable_tonedetect_da_alias: does%20not%20exist\n"
    "variable_tonedetect_da_accuracy: ACCURACY\n"
)


def selftest():
    print("== selftest: parse a sample CHANNEL_HANGUP_COMPLETE event ==")
    ev = parse_event_body(SAMPLE_EVENT)
    show(ev)
    assert ev["variable_tonedetect_da_category"] == "空号"
    assert ev["variable_tonedetect_da_alias"] == "does not exist"
    print("PASS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8021)
    ap.add_argument("--password", default="ClueCon")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        selftest()
        return

    try:
        ESL(args.host, args.port, args.password).loop()
    except KeyboardInterrupt:
        pass
    except (ConnectionError, OSError) as e:
        print(f"ESL connection failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
