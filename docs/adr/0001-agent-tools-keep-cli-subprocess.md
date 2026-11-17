# 0001 — Agent tools keep CLI subprocess

2026-11-16. Rejected: call skill code in-process instead of `tool_runtime.run_cli`.

- Subprocess = only kill switch. `CLI_TIMEOUTS` (`pdf-edit` 300 s) kills hung OCR/PDF child. In-process hang freezes bot, no recovery short of restart.
- `wechat.allowed_commands` allow-list enforced in `run_cli`.

Cost accepted: each parameter declared 3× (manifest `SCHEMAS`, argparse, db function); CLI tests spawn Python.

In-process fine where no hang risk and turn context needed: Mail_Keeper tools, `CONTEXT_FNS`.

Reopen if: tools get in-process cancellable timeout.
