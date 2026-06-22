# AGENTS.md

## Cursor Cloud specific instructions

This repo (`mod_tonedetect`) has three parts; see `README.md` for full architecture.
Commands below assume the update script has already run (system packages installed,
Python venv created at `server/.venv`).

### Components & how to lint/test/build/run

- **DSP core (C, offline)** — `src/tone_dsp.{c,h}`, `src/ws_client.{c,h}`, tests in `test/`.
  - Build + run the offline test suite from the repo root: `make test` (see root `Makefile`).
  - `make test` builds everything in `all`, which includes the `ws_stream_test` harness that
    links `libwebsockets`; the build fails without `libwebsockets-dev` (installed by the update script).
  - `make clean` removes `build/`.

- **Python recognition server (`server/`)** — the main runnable service. Uses the venv at `server/.venv`.
  - Activate with `. server/.venv/bin/activate` (created with `--system-site-packages`).
  - Run tests (no network needed; each is a standalone script, not pytest):
    `for t in server/tests/test_*.py; do python "$t"; done`
  - Run the service: `python -m tonedetect_server --host 127.0.0.1 --port 9977 --samples <dir> [--key KEY]`
    (run from inside `server/`, or with `server/` on `PYTHONPATH`).
  - There is no build step and no lint config for the Python side.

- **FreeSWITCH module (`module/`)** — thin integration layer; build is intentionally separate.
  - It requires FreeSWITCH dev headers (`/usr/include/freeswitch`) which are NOT installed here and
    are not in the standard apt repos. Running it end-to-end also needs a full FreeSWITCH daemon plus
    SIP gateways, so it is out of scope for this dev VM. Build it only against an installed FreeSWITCH:
    `cd module && make FS_INCLUDE=... FS_MODDIR=...`.
  - The module's logic lives in the decoupled `tone_dsp` / `ws_client` cores, which ARE fully
    buildable and testable offline here (`make test` + the `ws_stream_test` harness), so module
    behavior can be validated without FreeSWITCH.

### End-to-end "hello world" (pure local, no FreeSWITCH)

1. Generate a demo sample library + query WAVs: `python server/tests/make_demo_wavs.py /tmp/td_demo`
   (run from `server/`, or with `server/` on `PYTHONPATH`).
2. Start the server: `python -m tonedetect_server --port 9977 --samples /tmp/td_demo/samples` (from `server/`).
3. Stream a WAV and read the RESULT:
   `python examples/ws_client/stream_wav.py --url ws://127.0.0.1:9977/ --wav /tmp/td_demo/query_match.wav`
   → expect `tone=sample`, `category=空号`. The C client path is exercised by
   `./build/ws_stream_test ws://127.0.0.1:9977/ /tmp/td_demo/query_match.wav 空号`
   (the C harness sends no auth key, so point it at a server started WITHOUT `--key`).

### Gotchas

- The Python venv is created with `--system-site-packages` (intentional, per `server/README.md`).
- `--key` on the server enforces auth: the WS START must include a matching `key`. The example
  Python client takes `--key`; the C `ws_stream_test` harness does not send one, so test it against
  a keyless server instance.
