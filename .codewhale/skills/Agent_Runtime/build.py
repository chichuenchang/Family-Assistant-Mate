"""Build snapshot: freeze working tree so repo edits never reach running daemon.

Why: each tool call spawns `cli.py` fresh from disk; edit repo mid-run = next call runs it.
Design: docs/superpowers/specs/2026-11-16-build-snapshot-design.md.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import jsonfile

ROOT = Path(__file__).resolve().parents[3]
CODE_DIR = ".codewhale"
STAMP_FMT = "%Y%m%d-%H%M%S"
STAMP_RE = re.compile(r"^\d{8}-\d{6}$")   # = STAMP_FMT
TMP, DEL = ".tmp", ".del"                 # build in progress / delete in progress


class BuildError(RuntimeError):
    """Build refused; nothing left behind."""


def builds_dir() -> Path:
    """FA_BUILDS_DIR (tests) else sibling <repo>-builds/ (outside repo: no pytest/grep noise)."""
    env = os.environ.get("FA_BUILDS_DIR")
    return Path(env) if env else ROOT.parent / f"{ROOT.name}-builds"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def _git_lines(root: Path, *args: str) -> list[str]:
    out = _run(["git", "-c", "core.quotepath=off", *args], root)   # 中文名不转义
    if out.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {out.stderr.strip()}")
    return [ln for ln in out.stdout.splitlines() if ln]


def gate(root: Path) -> list[str]:
    """Gate: syntax errors (compileall) + pyflakes `undefined name`. [] = pass."""
    errors: list[str] = []
    comp = _run([sys.executable, "-m", "compileall", "-q", CODE_DIR], root)
    if comp.returncode:
        errors += [ln for ln in (comp.stdout + comp.stderr).splitlines() if ln.strip()]
    # -W: py3.12 SyntaxWarning (bad escape) lands on stderr, rc 0; not a gate error
    flakes = _run([sys.executable, "-W", "ignore::SyntaxWarning", "-m", "pyflakes", CODE_DIR], root)
    errors += [ln for ln in flakes.stdout.splitlines() if "undefined name" in ln]
    # stderr = pyflakes crashed / missing (or syntax error, already caught): never pass silently
    errors += [f"pyflakes: {ln}" for ln in flakes.stderr.splitlines() if ln.strip()]
    return errors


def git_state(root: Path) -> dict:
    """Commit + dirty flag + porcelain paths. Dirty warns, never blocks."""
    commit = _git_lines(root, "rev-parse", "--short", "HEAD")[0]
    dirty_files = [ln[3:] for ln in _git_lines(root, "status", "--porcelain")]
    return {"commit": commit, "dirty": bool(dirty_files), "dirty_files": dirty_files}


def _is_bytecode(rel: str) -> bool:
    return "__pycache__" in rel.split("/") or rel.endswith(".pyc")


def files_to_copy(root: Path) -> list[str]:
    """Working tree under .codewhale + config.json: tracked, untracked-not-ignored,
    plus ignored files under .codewhale (skill .env) minus bytecode."""
    not_ignored = _git_lines(root, "ls-files", "-co", "--exclude-standard", "--", CODE_DIR, "config.json")
    ignored = _git_lines(root, "ls-files", "-oi", "--exclude-standard", "--", CODE_DIR)
    return sorted(rel for rel in set(not_ignored) | set(ignored)
                  if not _is_bytecode(rel) and (root / rel).is_file())


def _link_data(root: Path, snap: Path) -> None:
    """<snap>/<data_root> junction → live <root>/<data_root>: same layout, ROOT = parents[3]
    unchanged. Absolute data_root needs no link."""
    rel = jsonfile.load_dict(root / "config.json").get("data_root") or "data"
    if Path(rel).is_absolute():
        return
    live = root / rel
    if not live.is_dir():
        raise BuildError(f"live data dir missing: {live}")
    link = snap / rel
    link.parent.mkdir(parents=True, exist_ok=True)
    out = _run(["cmd", "/c", "mklink", "/J", str(link), str(live)], snap)
    if out.returncode:
        raise BuildError(f"mklink /J failed: {(out.stdout + out.stderr).strip()}")


def _unlink_junctions(d: Path) -> None:
    """Unlink every junction under d; never descend into one (= live data)."""
    with os.scandir(d) as it:
        for e in it:
            if os.path.isjunction(e.path):
                os.rmdir(e.path)          # removes link only
            elif e.is_dir(follow_symlinks=False):
                _unlink_junctions(Path(e.path))


def remove_snapshot(path: Path) -> bool:
    """Delete snapshot; False = in use (untouched) or delete blocked (left as .del).
    Rename probe: measured WinError 32 while a process has cwd in the dir (daemon:
    run-daemon sets cwd = snapshot; CLIs inherit). rmtree alone would empty it first.
    .del name never matches STAMP_RE: half-deleted dir never picked by latest().
    Junctions unlinked before rmtree: never walks into live data."""
    if not path.is_dir():
        return True
    if not path.name.endswith(DEL):
        try:
            path = path.rename(path.with_name(path.name + DEL))
        except OSError:
            return False
    try:
        _unlink_junctions(path)
        shutil.rmtree(path)
    except OSError:
        return False
    return True


def prune(builds: Path, keep: int = 5) -> list[str]:
    """Drop all but newest `keep` builds + crashed .tmp / leftover .del. Returns skipped."""
    if not builds.is_dir():
        return []
    stamps = sorted(p for p in builds.iterdir() if STAMP_RE.match(p.name))
    junk = [p for p in builds.iterdir() if p.suffix in (TMP, DEL)]
    return [p.name for p in stamps[:-keep] + junk if not remove_snapshot(p)]


def make_snapshot(root: Path, builds: Path, stamp: str, state: dict) -> Path:
    """Copy into <stamp>.tmp, link data, write BUILD.json (id + `git_state`), rename.
    Fail = nothing left."""
    final = builds / stamp
    if final.exists():
        raise BuildError(f"build {stamp} exists")
    tmp = builds / f"{stamp}{TMP}"
    try:
        tmp.mkdir(parents=True)
        for rel in files_to_copy(root):
            dest = tmp / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / rel, dest)
        _link_data(root, tmp)
        (tmp / "BUILD.json").write_text(
            json.dumps({"id": stamp, **state}, ensure_ascii=False, indent=1),
            encoding="utf-8")
        tmp.rename(final)
    except BaseException:
        remove_snapshot(tmp)
        raise
    return final


def latest(builds: Path) -> Path | None:
    """Newest complete build (stamp name + BUILD.json); .tmp / partial ignored."""
    done = [p for p in builds.glob("*")
            if STAMP_RE.match(p.name) and (p / "BUILD.json").is_file()] if builds.is_dir() else []
    return max(done, key=lambda p: p.name, default=None)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Snapshot code for /run-daemon.")
    ap.add_argument("--latest", action="store_true", help="print newest build path")
    args = ap.parse_args(argv)
    builds = builds_dir()
    if args.latest:
        snap = latest(builds)
        if snap is None:
            print("no build", file=sys.stderr)
            return 1
        print(snap)
        return 0
    errors = gate(ROOT)
    if errors:
        print("BUILD FAILED, no snapshot:", *errors, sep="\n")
        return 1
    state = git_state(ROOT)
    if state["dirty"]:
        print(f"WARNING dirty: {len(state['dirty_files'])} uncommitted — commit when ready",
              *(f"  {f}" for f in state["dirty_files"]), sep="\n")
    try:
        snap = make_snapshot(ROOT, builds, datetime.now().strftime(STAMP_FMT), state)
    except BuildError as e:
        print(f"BUILD FAILED: {e}")
        return 1
    print(f"built {snap.name} ({state['commit']}{' dirty' if state['dirty'] else ''}) -> {snap}")
    for name in prune(builds):
        print(f"skipped {name} (in use)")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
