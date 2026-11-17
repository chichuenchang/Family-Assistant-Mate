# Project Secrets File Implementation Plan

> **For agentic workers:** executed inline (user: no subagents), superpowers:executing-plans. Steps use `- [ ]`.

**Goal:** all FAM secrets from gitignored `.codewhale/.env`, overriding Windows env.
**Architecture:** `Agent_Runtime/project_env.py` loads file into `os.environ`; `bootstrap.py` calls it, so every entry point gets it.
**Tech Stack:** Python 3.10 stdlib (`winreg` for import).
**Spec:** `docs/superpowers/specs/2026-11-17-project-secrets-design.md`

## Global Constraints
- File wins over process env; empty value in file ignored.
- Never print secret values (import CLI prints names only).
- Tests never read real `.codewhale/.env` (`FAM_ENV_FILE`).
- Docs caveman ultra, fact once. Commits: 5 words, no trailer.

## Review Focus
- Notepad BOM / CRLF / quoted value / `export`-less `KEY = value` spacing: parsed same as Any_Search loader.
- `set_key` on missing file creates it; on existing key replaces line in place, keeps comments/order.
- Custom `cred_prefix` (`members.json`) names like `ALICE_GMAIL_REFRESH_TOKEN`: `--import-windows` must catch by suffix.
- `--import-windows` never clobbers value already in file.
- `ocr.py` run directly sees `TENCENT_*` from file.

---

### Task 1: loader + hook

**Files:** Create `.codewhale/skills/Agent_Runtime/project_env.py`, `.codewhale/.env.example`, `tests/test_project_env.py`. Modify `Agent_Runtime/bootstrap.py` (end), `tests/conftest.py` (before `import bootstrap`), `.gitignore`.

**Interfaces (produces):**
- `ENV_FILE_VAR = "FAM_ENV_FILE"`
- `env_path() -> Path` — `$FAM_ENV_FILE` else `.codewhale/.env`
- `parse(text: str) -> dict[str, str]`
- `load(path: Path | None = None) -> list[str]` — names applied
- `set_key(name: str, value: str, path: Path | None = None) -> Path` — upsert, atomic (`tmp` + `os.replace`), also sets `os.environ`

- [ ] Tests: `test_parse_bom_comments_quotes` (`"﻿A=1\r\n# c\nB = \"two\"\nC=\n"` → `{"A":"1","B":"two"}`), `test_load_overrides_env`, `test_load_missing_file_noop`, `test_set_key_creates_file`, `test_set_key_replaces_in_place` (comment + other key order kept), `test_env_path_override`.
- [ ] Run `python -m pytest tests/test_project_env.py -q`: FAIL (module missing).
- [ ] Implement; bootstrap end: `import project_env; project_env.load()`; conftest sets `os.environ["FAM_ENV_FILE"]` to nonexistent tmp path; `.gitignore` adds `.codewhale/.env`; `.env.example` lists names, header points to `Agent_Runtime/SKILL.md`「环境变量」.
- [ ] Full suite `conda run -n familyassis310 python -m pytest -q`: PASS.
- [ ] Commit `Add project env secrets loader`.

### Task 2: `--import-windows`

**Files:** Modify `project_env.py`, `tests/test_project_env.py`.

**Interfaces:** `import_windows(path: Path | None = None, read: Callable[[], dict[str,str]] = _read_hkcu) -> list[str]`. Selected names: keys in `.env.example` ∪ regex `^[A-Z0-9_]+_(API_KEY|BASE_URL|CLIENT_ID|CLIENT_SECRET|REFRESH_TOKEN|BOT_TOKEN|SECRET_ID|SECRET_KEY)$`. Skip names non-empty in file. `__main__`: `--import-windows` prints imported names + reminder to delete old `setx` vars.

- [ ] Tests: `test_import_selects_known_and_suffix` (`ALICE_GMAIL_REFRESH_TOKEN` in, `Path`/`TEMP` out), `test_import_keeps_existing_file_value`.
- [ ] Run: FAIL. Implement. Run: PASS.
- [ ] Commit `Import Windows env into file`.

### Task 3: writers + OCR order

**Files:** Modify `Agent_Runtime/google_oauth.py` (`run_loopback_auth` tail + missing-client message), `Agent_Runtime/telegram_bot.py:312`, `OCR/ocr.py` (bootstrap import above `SECRET_ID`; drop one in `main`; error text).

- [ ] `run_loopback_auth`: `project_env.set_key(f"{prefix}_REFRESH_TOKEN", refresh)`, print path, no token echo.
- [ ] Messages say "填 `.codewhale/.env`" not `setx`/环境变量.
- [ ] `python -m pyflakes` on changed files clean; full suite PASS.
- [ ] Manual: `FAM_ENV_FILE=<tmp>` with `TENCENT_SECRET_ID=x` + `TENCENT_SECRET_KEY=y`, `python -c` import ocr via path, `ocr.is_available()` → True.
- [ ] Commit `Write tokens to project env`.

### Task 4: launcher + docs

**Files:** `.claude/commands/run-daemon.md`, `README.md` (setx blocks), `FAM.md`「Google 凭据丢失」, SKILL.md: `Agent_Runtime` (table heading, Telegram line 180), `Remote_Backup`, `Calendar_Keeper`, `Mail_Keeper`, `OCR`, `Any_Search`, `Web_Reach` (central file also works). Memory `gdrive-gcal-shared-oauth-client`.

- [ ] Remove HKCU re-read from `$cmd` + its note.
- [ ] Replace `setx X "…"` with `X=…` in `.codewhale/.env`; one pointer, no repeated key lists.
- [ ] `grep -rn setx` outside `docs/` and `tests/`: none left except migration mention.
- [ ] Commit `Docs point to project env`.
