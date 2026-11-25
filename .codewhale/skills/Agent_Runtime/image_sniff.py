"""FAM — 按魔数判图片格式（扩展名不可信：微信存图常 .jpg 实为 png）。"""

from __future__ import annotations

_MAGIC = ((b"\xff\xd8\xff", "jpeg"), (b"\x89PNG", "png"), (b"GIF8", "gif"))


def image_format(data: bytes) -> str | None:
    """jpeg / png / gif / webp；其余 None。"""
    fmt = next((f for magic, f in _MAGIC if data.startswith(magic)), None)
    if fmt is None and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        fmt = "webp"
    return fmt
