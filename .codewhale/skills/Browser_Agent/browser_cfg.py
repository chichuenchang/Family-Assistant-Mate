"""config.json `browser` 块（键义见其 _comment）：缺键取 DEFAULTS，未知键丢弃。Chrome、循环、任务共用。"""

from __future__ import annotations

import tool_runtime as rt

DEFAULTS = {"exe": "", "port": 9333, "model": "", "effort": "medium", "max_steps": 60,
            "timeout_s": 900, "idle_close_min": 30, "humanize": True, "speed": 1.0,
            "max_sent_shots": 8}


def load(config: dict | None = None) -> dict:
    block = (rt.CONFIG if config is None else config).get("browser") or {}
    return {**DEFAULTS, **{k: v for k, v in block.items() if k in DEFAULTS}}
