"""项目密钥文件 .codewhale/.env（gitignore）：FAM 自带全部 key，不靠 Windows 用户环境变量。

bootstrap 末尾 load()：文件非空值**覆盖** os.environ（残留 setx 值不再遮住文件）。
键名与含义：.codewhale/.env.example → Agent_Runtime/SKILL.md「环境变量」。
测试钩子 FAM_ENV_FILE 换文件路径（conftest 指向不存在的文件，真 key 不进测试）。
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_FILE_VAR = "FAM_ENV_FILE"
_CODEWHALE = Path(__file__).resolve().parents[2]


def env_path() -> Path:
    p = os.environ.get(ENV_FILE_VAR)
    return Path(p) if p else _CODEWHALE / ".env"


def _split(line: str) -> tuple[str, str] | None:
    """`KEY=value` → (KEY, value)；注释/空行/无 = → None。值去引号。"""
    line = line.strip().lstrip("﻿")
    if not line or line.startswith("#") or "=" not in line:
        return None
    k, _, v = line.partition("=")
    return k.strip(), v.strip().strip("\"'").strip()


def parse(text: str) -> dict[str, str]:
    """非空值才收。utf-8-sig 读入后 BOM 已去；此处再兜一次（直接传 str 时）。"""
    out = {}
    for line in text.splitlines():
        kv = _split(line)
        if kv and kv[0] and kv[1]:
            out[kv[0]] = kv[1]
    return out


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except (FileNotFoundError, NotADirectoryError):
        return ""


def load(path: Path | None = None) -> list[str]:
    """文件值写入 os.environ（覆盖）。返回生效键名；文件缺失 → []。"""
    values = parse(_read(path or env_path()))
    os.environ.update(values)
    return list(values)


def set_key(name: str, value: str, path: Path | None = None) -> Path:
    """upsert 一行：已有键原位替换（保留注释与顺序），否则追加。原子写；同步 os.environ。"""
    path = path or env_path()
    lines = _read(path).splitlines()
    new = f"{name}={value}"
    for i, line in enumerate(lines):
        kv = _split(line)
        if kv and kv[0] == name:
            lines[i] = new
            break
    else:
        lines.append(new)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    os.environ[name] = value
    return path
