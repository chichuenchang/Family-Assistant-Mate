"""项目密钥文件 .codewhale/.env（gitignore）：FAM 自带全部 key，不靠 Windows 用户环境变量。

bootstrap 末尾 load()：文件非空值**覆盖** os.environ（残留 setx 值不再遮住文件）。
键名与含义：.codewhale/.env.example → Agent_Runtime/SKILL.md「环境变量」。
测试钩子 FAM_ENV_FILE 换文件路径（conftest 指向不存在的文件，真 key 不进测试）。
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Callable

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
    """upsert 一行：首个同名行原位替换（保留注释与顺序），其余同名行删（parse 后者胜，留着会遮新值）；
    无则追加。原子写；同步 os.environ。"""
    path = path or env_path()
    new = f"{name}={value}"
    lines: list[str] = []
    placed = False
    for line in _read(path).splitlines():
        kv = _split(line)
        if kv and kv[0] == name:
            if placed:
                continue
            line, placed = new, True
        lines.append(line)
    if not placed:
        lines.append(new)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    os.environ[name] = value
    return path


# ── 一次性迁移：Windows 用户环境变量 → 文件 ────────────────────

# Google 自定义前缀（members.json cred_prefix）按后缀认；别的 *_API_KEY 多属其他 agent，不收
_GOOGLE_CRED = re.compile(r"^[A-Z0-9_]+_(CLIENT_ID|CLIENT_SECRET|REFRESH_TOKEN)$")


def _known_names() -> set[str]:
    """.env.example 键 + config.json llm.models 的 api_key_env / base_url_env。"""
    names = {kv[0] for line in _read(_CODEWHALE / ".env.example").splitlines()
             if (kv := _split(line))}
    try:
        models = json.loads(_read(_CODEWHALE.parent / "config.json") or "{}").get("llm", {}).get("models", {})
    except ValueError:
        models = {}
    for spec in models.values():
        if isinstance(spec, dict):
            names.update(spec[k] for k in ("api_key_env", "base_url_env") if spec.get(k))
    return names


def _read_hkcu() -> dict[str, str]:
    import winreg
    out = {}
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
        i = 0
        while True:
            try:
                name, value, _ = winreg.EnumValue(k, i)
            except OSError:
                return out
            out[name] = str(value)
            i += 1


def import_windows(path: Path | None = None,
                   read: Callable[[], dict[str, str]] = _read_hkcu) -> list[str]:
    """HKCU 里 FAM 认识的键写入文件；文件已有非空值的键不动。返回写入键名。"""
    path = path or env_path()
    have = parse(_read(path))
    known = _known_names()
    names = []
    for name, value in read().items():
        if value and name not in have and (name in known or _GOOGLE_CRED.match(name)):
            set_key(name, value, path)
            names.append(name)
    return names


if __name__ == "__main__":
    if sys.argv[1:] != ["--import-windows"]:
        sys.exit("用法: python project_env.py --import-windows")
    names = import_windows()
    print(f"写入 {env_path()}：" + (", ".join(names) or "无新键"))
    if names:
        print("确认 bot 正常后可删旧变量：[Environment]::SetEnvironmentVariable('<名>', $null, 'User')")
