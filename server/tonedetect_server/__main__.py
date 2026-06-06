"""命令行入口: python -m tonedetect_server --host 0.0.0.0 --port 9977 --samples ./samples"""
from __future__ import annotations

import argparse
import asyncio
import logging

from .matcher import SampleLibrary
from .server import serve


def main():
    ap = argparse.ArgumentParser(description="tonedetect WebSocket recognition server")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=9977)
    ap.add_argument("--samples", default=None, help="sample library directory (with samples.json)")
    ap.add_argument("--capture-dir", default=None,
                    help="directory to save un-matched (prompt) segments for later labeling")
    ap.add_argument("--key", default=None, help="auth key required in START")
    ap.add_argument("--accuracy", type=float, default=0.75)
    ap.add_argument("--inaccuracy", type=float, default=0.60)
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    library = SampleLibrary(samples_dir=args.samples,
                            accuracy_threshold=args.accuracy,
                            inaccuracy_threshold=args.inaccuracy)

    try:
        asyncio.run(serve(args.host, args.port, library, key=args.key, capture_dir=args.capture_dir))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
