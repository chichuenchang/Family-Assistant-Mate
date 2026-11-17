# Build Snapshot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (user forbids subagents). Steps use checkbox (`- [ ]`) syntax.

**Goal:** `/build` freezes working tree into snapshot; `/run-daemon` runs newest snapshot.

**Architecture:** One stdlib script `build.py` (gate, copy, junction, BUILD.json, prune, `--latest`). Two slash commands call it.

**Tech Stack:** Python 3.12 (familyassis310), git CLI, `cmd /c mklink /J`, pytest.

**Spec:** `docs/superpowers/specs/2026-11-16-build-snapshot-design.md`

## Global Constraints

- Interpreter `C:\Users\slimj\anaconda3\envs\familyassis310\python.exe`; tests `-m pytest`.
- Stdlib only (pyflakes already installed in env; invoked via subprocess).
- Commits: exactly 5 words, one line, no Co-Authored-By. `git add` only files this plan touches (pre-existing simplify edits stay uncommitted).
- Keep newest 5 builds. Stamp `%Y%m%d-%H%M%S`.
- Comments/docs caveman-terse.

## Review Focus

1. Prune deleting through `data` junction → live data lost. Test: data file survives `remove_snapshot` (Task 3).
2. Snapshot of running daemon pruned. Test: Popen with `cwd=snapshot` → skipped, dir intact (Task 3).
3. Crashed build leaves `<stamp>.tmp` → `--latest` must ignore; prune cleans it safely (Tasks 2, 3).
4. Live data dir missing (fresh clone) → build fails clearly, no snapshot (Task 2).
5. Same-second rebuild → error, existing snapshot untouched (Task 2).

---

### Task 1: Gate, git state, file selection

**Files:**
- Create: `.codewhale/skills/Agent_Runtime/build.py`
- Test: `tests/test_build.py`

**Interfaces — Produces:**
- `ROOT: Path` (= `parents[3]`)
- `check(root: Path) -> list[str]` — error lines; `[]` = pass. compileall `-q` on `root/.codewhale` (nonzero → its output lines); pyflakes lines containing `undefined name`.
- `git_state(root: Path) -> dict` — `{"commit": short sha, "dirty": bool, "dirty_files": [porcelain paths]}`.
- `files_to_copy(root: Path) -> list[str]` — sorted posix rel paths: `git ls-files -co --exclude-standard -- .codewhale config.json` ∪ `git ls-files -oi --exclude-standard -- .codewhale` minus anything with `__pycache__` segment or `.pyc` suffix. Skip paths not existing on disk (deleted-but-tracked).

Test fixture `repo(tmp_path)`: `git init`, user config, files `.codewhale/skills/X/cli.py`, `.codewhale/skills/X/.env`, `.codewhale/skills/X/__pycache__/a.pyc`, `config.json` `{"data_root": "data"}`, `tests/t.py`, `.gitignore` (`data/`, `__pycache__/`, `*.pyc`, `**/X/.env`), `data/f.txt`; commit.

- [ ] Step 1: tests
  - `test_files_include_untracked_and_ignored_env`: add untracked `.codewhale/skills/X/new.py` → result contains `cli.py`, `new.py`, `.env`, `config.json`; excludes `tests/t.py`, `.gitignore`, any `__pycache__`, `data/f.txt`.
  - `test_git_state_clean_then_dirty`: clean → `dirty False`, `dirty_files == []`; edit cli.py → `dirty True`, `".codewhale/skills/X/cli.py" in dirty_files`.
  - `test_check_flags_syntax_error` (write `bad.py` `def(:`) → non-empty; `test_check_flags_undefined_name` (`print(nope)`) → line containing `undefined name`; `test_check_passes_clean_tree` → `[]`.
- [ ] Step 2: run `python -m pytest tests/test_build.py -q` → FAIL (import error).
- [ ] Step 3: implement the three functions.
- [ ] Step 4: run → PASS.
- [ ] Step 5: commit `Add build gate and selection`.

### Task 2: Snapshot, junction, latest, CLI

**Files:** Modify `build.py`; Test `tests/test_build.py`.

**Interfaces — Produces:**
- `builds_dir() -> Path` — env `FA_BUILDS_DIR` else `ROOT.parent / f"{ROOT.name}-builds"`.
- `make_snapshot(root: Path, builds: Path, stamp: str) -> Path` — raises `BuildError` (RuntimeError subclass) if `builds/stamp` exists or live data dir missing. Copies `files_to_copy` into `builds/<stamp>.tmp` (copy2), junction `<tmp>/<data_root>` → `root/<data_root>` when `data_root` relative (read from `root/config.json`, default `data`), writes `BUILD.json` `{"id": stamp, **git_state}`, renames to `builds/<stamp>`. Any failure: `remove_snapshot(tmp)` then re-raise.
- `latest(builds: Path) -> Path | None` — newest dir whose name matches `^\d{8}-\d{6}$` and has `BUILD.json`.
- `main(argv=None) -> int` — `--latest`: print path or stderr `no build` + return 1. Default: `check` (fail → print, return 1, no snapshot) → `git_state` dirty → print `WARNING dirty: N uncommitted` + files → `make_snapshot` → print `built <id> -> <path>`. (Prune wired in Task 3.)

- [ ] Step 1: tests
  - `test_snapshot_layout`: snapshot has `.codewhale/skills/X/cli.py`, `config.json`, `BUILD.json` with `id`/`commit`/`dirty`; no `tests/`; `os.path.isjunction(snap/"data")`; `(snap/"data"/"f.txt").read_text()` equals live.
  - `test_snapshot_isolated_from_edits`: edit repo cli.py after build → snapshot copy unchanged.
  - `test_existing_stamp_raises`: second `make_snapshot` same stamp → `BuildError`; first snapshot intact.
  - `test_missing_data_raises_no_leftover`: remove `data/` → `BuildError`; `builds` has no entries.
  - `test_latest_ignores_tmp_and_incomplete`: create `20990101-000000.tmp` and `20990101-000001` without BUILD.json plus real snapshot → `latest` returns real one.
  - `test_main_check_fail_no_snapshot` (monkeypatch `ROOT`, `FA_BUILDS_DIR`, add syntax error) → returns 1, builds empty.
- [ ] Step 2: run → FAIL.
- [ ] Step 3: implement.
- [ ] Step 4: run → PASS.
- [ ] Step 5: commit `Create snapshot with live data`.

### Task 3: Safe removal, prune

**Files:** Modify `build.py`; Test `tests/test_build.py`.

**Interfaces — Produces:**
- `remove_snapshot(path: Path) -> bool` — rename `path` → `path.with_name(path.name + ".del")` (skip rename if already `.del`); `OSError` → `False`, untouched. Then every child `os.path.isjunction` → `os.rmdir` it; then `shutil.rmtree`. Returns `True`.
- `prune(builds: Path, keep: int = 5) -> list[str]` — stamp dirs sorted, all but newest `keep`, plus any `*.tmp` / `*.del` dirs, through `remove_snapshot`; returns names skipped (in use). `main` calls it after build, prints `skipped <name> (in use)` per skip.

- [ ] Step 1: tests
  - `test_remove_keeps_live_data`: after `remove_snapshot(snap)` → snapshot gone, live `data/f.txt` still exists.
  - `test_remove_skips_in_use`: `Popen([sys.executable, "-c", "import time; time.sleep(30)"], cwd=snap)` → `remove_snapshot` returns `False`, `snap/BUILD.json` exists; kill proc in `finally`.
  - `test_prune_keeps_newest_five`: 7 snapshots + one `.tmp` (with junction) → 5 newest remain, `.tmp` gone, live data intact.
- [ ] Step 2: run → FAIL.
- [ ] Step 3: implement; wire `prune` into `main`.
- [ ] Step 4: run full `python -m pytest -q` → PASS.
- [ ] Step 5: commit `Prune old builds, spare running`.

### Task 4: Commands, docs, real run

**Files:**
- Create: `.claude/commands/build.md`
- Modify: `.claude/commands/run-daemon.md`
- Modify: `.codewhale/skills/Agent_Runtime/SKILL.md` (one line near launch section)
- Modify: `build.py` docstring (facts: why, junction, prune rule) — single source.

`build.md`: run `& <py> .codewhale/skills/Agent_Runtime/build.py` from repo; reply build id + dirty warning verbatim (remind to commit) or exact failure.
`run-daemon.md`: `$b = & <py> .codewhale/skills/Agent_Runtime/build.py --latest`; empty → reply `no build — run /build`; else `Start-Process -WorkingDirectory $b`, title `WeChat Bot <leaf of $b>`, script `.codewhale/skills/Agent_Runtime/wechat_ilink.py` (relative to cwd = snapshot), keep HKCU env re-read and `$ARGUMENTS`.

- [ ] Step 1: write files.
- [ ] Step 2: real `build.py` run → prints `built <id>`, dirty warning (simplify edits); `--latest` prints that path; snapshot `data` junction lists live files.
- [ ] Step 3: smoke import from snapshot: `& <py> -c "import sys; sys.path.insert(0, r'<snap>\.codewhale\skills\Agent_Runtime'); import paths; print(paths.data_root().resolve())"` → live data path. (Do not launch bot.)
- [ ] Step 4: commit `Add build and run commands`.
