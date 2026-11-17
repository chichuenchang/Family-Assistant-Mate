"""Build snapshot: freeze working tree so repo edits never reach running daemon.

Why: each tool call spawns `cli.py` fresh from disk; edit repo mid-run = next call runs it.
Design: docs/superpowers/specs/2026-11-16-build-snapshot-design.md.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CODE_DIR = ".codewhale"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def _git_lines(root: Path, *args: str) -> list[str]:
    out = _run(["git", "-c", "core.quotepath=off", *args], root)   # 中文名不转义
    if out.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {out.stderr.strip()}")
    return [ln for ln in out.stdout.splitlines() if ln]


def check(root: Path) -> list[str]:
    """Gate: syntax errors (compileall) + pyflakes `undefined name`. [] = pass."""
    errors: list[str] = []
    comp = _run([sys.executable, "-m", "compileall", "-q", CODE_DIR], root)
    if comp.returncode:
        errors += [ln for ln in (comp.stdout + comp.stderr).splitlines() if ln.strip()]
    flakes = _run([sys.executable, "-m", "pyflakes", CODE_DIR], root)
    errors += [ln for ln in flakes.stdout.splitlines() if "undefined name" in ln]
    return errors


def git_state(root: Path) -> dict:
    """Commit + dirty flag + porcelain paths. Dirty warns, never blocks."""
    commit = _git_lines(root, "rev-parse", "--short", "HEAD")[0]
    dirty_files = [ln[3:] for ln in _git_lines(root, "status", "--porcelain")]
    return {"commit": commit, "dirty": bool(dirty_files), "dirty_files": dirty_files}


def _skip(rel: str) -> bool:
    return "__pycache__" in rel.split("/") or rel.endswith(".pyc")


def files_to_copy(root: Path) -> list[str]:
    """Working tree under .codewhale + config.json: tracked, untracked-not-ignored,
    plus ignored files under .codewhale (skill .env) minus bytecode."""
    tracked = _git_lines(root, "ls-files", "-co", "--exclude-standard", "--", CODE_DIR, "config.json")
    ignored = _git_lines(root, "ls-files", "-oi", "--exclude-standard", "--", CODE_DIR)
    return sorted(rel for rel in set(tracked) | set(ignored)
                  if not _skip(rel) and (root / rel).is_file())
