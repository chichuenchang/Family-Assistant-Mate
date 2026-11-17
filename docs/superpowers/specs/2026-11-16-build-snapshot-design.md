# Build snapshot for daemon

Why: tools spawn `cli.py` subprocess per call, read from disk each time. Edit repo while bot runs → next tool call runs edited (maybe half-written) code. `/build` freezes code; `/run-daemon` runs newest freeze.

## Decided (user)

- Snapshot = working tree as on disk (uncommitted + untracked-not-ignored), not HEAD.
- `/build` checks git; dirty → warn + list files, never block. Claude never commits.

## Approaches

- **Picked: copy + `data` junction.** Same layout as repo, so `ROOT = parents[3]` (~15 modules) needs zero change.
- Rejected zipapp: CLIs run by file path, `Path(__file__).parents[3]/config.json` breaks in zip.
- Rejected `git stash create` + worktree: drops untracked files.
- Rejected `DATA_ROOT` env: `backup_sync`, `models`, `doc_models` read `ROOT/...` directly; ~15 edits.

## Design (Claude's calls, approved)

- Script `.codewhale/skills/Agent_Runtime/build.py`; command `.claude/commands/build.md`.
- Builds dir `<repo>/../FamilyAssistant-builds/<YYYYMMDD-HHMMSS>/` (outside repo: no pytest/grep noise). Env `FA_BUILDS_DIR` overrides (tests).
- Gate before copy, fail = no snapshot: `compileall -q .codewhale`; `pyflakes .codewhale` lines with `undefined name`. No pytest.
- Copy: `git ls-files -co --exclude-standard -- .codewhale config.json`, plus git-ignored files under `.codewhale` except `__pycache__`/`*.pyc` (today: `Any_Search/.env`, `Web_Reach/.env`). No tests/, docs/.
- Live data: junction `<snapshot>/<config data_root>` → `<repo>/<data_root>` (`mklink /J`, no admin). Absolute `data_root` → no junction. All state (WeChat creds, logs, members, DBs) lives under data/ — verified.
- Atomic: build into `<stamp>.tmp`, rename when complete. `BUILD.json` = `{id, commit, dirty, dirty_files}`.
- `/run-daemon`: newest dir matching stamp pattern with `BUILD.json`; cwd = snapshot. No builds → error, no fallback to repo.
- Prune: keep newest 5. Per old dir: rename-probe (fails when a process has cwd inside = running daemon) → skip + report. Remove junction link first (`os.path.isjunction` + `os.rmdir`), then `rmtree`. **Never recurse into live data** — test-covered.

## Non-goals

Rollback flag, Telegram launcher, running pytest in build.
