# Project secrets file — design

## Why
FAM self-contained, like user's other agents. Keys live in project, not Windows `HKCU:\Environment` (`setx`).

## Goals / non-goals
- All secrets FAM reads (LLM, Tencent OCR, Google OAuth client + refresh tokens, Telegram, search) in one file.
- File wins over process env: leftover `setx` value never shadows it.
- Non-goal: encryption, OS keychain.
- Anti-goal: key reaching git, or `data/` (Remote_Backup uploads it).

## Approaches
- **A (picked):** one gitignored `.codewhale/.env`, loaded into `os.environ` at startup. Existing `os.environ.get` callers untouched; `/build` already copies ignored files under `.codewhale/`.
- B: `config.json` `secrets` block. Rejected: tracked file.
- C: per-skill `.env`. Rejected: scattered, Google client duplicated across Drive/Calendar/Gmail.

## Design
- New `Agent_Runtime/project_env.py` (not `secrets.py`: shadows stdlib). `load()`: parse `KEY=value`, `#` comments, quotes stripped, `utf-8-sig`; non-empty value overwrites `os.environ`. `set_key(name, value)`: upsert line, atomic write.
- `bootstrap.py` calls `project_env.load()`. Every entry point already imports `bootstrap`: one hook.
- Test hook `FAM_ENV_FILE` overrides path (like `DATA_ROOT`); `tests/conftest.py` points it at nonexistent file before `import bootstrap`, so real keys never enter tests.
- `.gitignore`: `.codewhale/.env`. Tracked `.codewhale/.env.example` lists every key name, one comment each — single source; README/SKILL.md setup steps point to it, `setx` lines removed.
- `google_oauth.py --auth`: `project_env.set_key("<PREFIX>_REFRESH_TOKEN", …)` instead of printing `setx`. Same for `telegram_bot.py` setup hint.
- `/run-daemon`: drop `HKCU:\Environment` re-read + its note.
- One-off `python project_env.py --import-windows`: copy names listed in `.env.example` from `HKCU:\Environment` (`winreg`) into file, skip names already set. Deleting old `setx` vars: user.
- `Any_Search` / `Web_Reach` keys may move to central file; their own `.env` loaders stay as fallback.

## Left to builder
- `OCR/ocr.py` reads `TENCENT_SECRET_*` at module level (line 45) before its `import bootstrap` (line 316): reorder or read lazily.
- Other module-level reads (`telegram_bot.TOKEN`) fine: after `bootstrap`.
- `FAM.md` "Google 凭据丢失" + memory `gdrive-gcal-shared-oauth-client` mention `setx`: update to file.
