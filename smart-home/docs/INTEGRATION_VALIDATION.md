# Fall Detection integration validation

Validated on 2026-10-27 with isolated Python 3.13.7 and Node.js 22.14.0 environments.

| Check | Result |
|---|---|
| `python -m pytest -q tests --tb=short` | 13 passed; one third-party deprecation warning |
| `python -m compileall -q app fallguard ../run_dashboard.py` | Passed |
| `node node_modules/typescript/bin/tsc --noEmit` | Passed |
| `node node_modules/next/dist/bin/next build` | Passed; all 7 static pages generated |
| Production Next.js proxy with headless Edge | Passed HTTP API and authenticated WebSocket connectivity |
| Browser workflow | Login, camera frame/overlay, AI activation, confirmed fall, shared banner/history, acknowledgement, logout passed |
| Mobile layout | 390px viewport checked; no horizontal overflow |
| Browser runtime exceptions | Zero in the tested workflow |

The Next.js dependency was updated from 14.2.18 to 14.2.35, following the
[official patch guidance](https://nextjs.org/blog/security-update-2025-12-11).

Tests use simulated camera frames and a classifier returning deterministic scores.
They validate integration behavior, not model accuracy. Real Android USB capture,
CUDA, live Telegram delivery and the ESP32 firmware build/flash were not tested.
The original trained model weights and 32-pose/55-feature tracker are reused.

`START_DASHBOARD.bat` requires Python 3.13 and Node.js to be installed. The validation
toolchains live in a temporary directory and do not install those prerequisites
globally. The hardware alarm requires flashing the updated firmware.
