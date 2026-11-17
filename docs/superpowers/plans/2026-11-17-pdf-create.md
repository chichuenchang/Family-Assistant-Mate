# PDF Create Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (user rule: no subagents). Steps use checkbox (`- [ ]`) syntax.

**Goal:** Agent tool `create_pdf`: FAM-written HTML/CSS → PDF via headless Edge/Chrome, sent with page-1 PNG preview.

**Architecture:** `PDF_Editor/pdf_create.py` (sanitize, browser find/render, preview, session dir) + CLI `pdf-create` + manifest callable that hands HTML over by temp file (argv limit). Registry `DOC_TOOLS` contract extended: `预览: <path>` lines → images.

**Tech Stack:** stdlib `subprocess`/`re`/`base64`, Edge/Chrome headless, pypdfium2 (preview).

**Spec:** `docs/superpowers/specs/2026-11-17-pdf-create-design.md`

## Global Constraints

- Interpreter: `conda run -n familyassis310 python -m pytest` — no skips allowed there (Edge present).
- CSP exact: `default-src 'none'; img-src data:; style-src 'unsafe-inline'; font-src data:`.
- Browser flags (verified Edge 157, 3 s): `--headless --disable-gpu --no-pdf-header-footer --user-data-dir=<temp> --print-to-pdf=<out> <file url>`. Temp profile dir mandatory: shared profile hands job to running Edge.
- Session dir: `data/<member>/pdf_creates/<id>/`, id regex `[0-9]{8}_[0-9]{6}_[0-9a-f]{4}` (same as `pdf_plan._ID_RE`).
- Output contract: line 1 = PDF data-relative path; `预览: <png rel>`; `session=<id>`; `警告:`/`提示:` lines.
- Commits: none by Claude (user handles git).

## Review Focus

- HTML fragment without `<html>/<head>` → CSP still injected, renders.
- `<img src>` remote URL, `file:///`, other member's path → tag removed + `警告:`; never fetched.
- `<meta http-equiv="refresh">` / `<base>` → stripped (navigation not covered by CSP; could print local files).
- HTML > 32k chars → travels by temp file, not argv.
- Browser hangs → killed at timeout, `[错误]`, temp dir cleaned.

---

### Task 1: Paths + registry preview lines

**Files:**
- Modify: `.codewhale/skills/Agent_Runtime/paths.py` (after `member_pdf_edits_dir`; module docstring layout line)
- Modify: `.codewhale/skills/Agent_Runtime/skill_registry.py:14,126-128`
- Test: `tests/test_paths.py`, `tests/test_pdf_agent.py`

**Interfaces:**
- Produces: `paths.member_pdf_creates_dir(member: str) -> Path` (creates). `ToolOutcome.images` gets `预览: ` lines of DOC_TOOLS results.

- [ ] Test `test_member_pdf_creates_dir_created`: `paths.member_pdf_creates_dir("Alex Lee")` is dir, posix endswith `data/Alex/pdf_creates`.
- [ ] Test `test_doc_tool_preview_lines_become_images`: tool_map `edit_pdf` stub returns `"a/x.pdf\n预览: a/p.png\nsession=1"` → `out.docs == ["a/x.pdf"]`, `out.images == ["a/p.png"]`.
- [ ] Run both: FAIL.
- [ ] Implement; docstring line 14: `成功返回首行 = 文件相对路径（传输层发文件）；"预览: <路径>" 行 = 附图`.
- [ ] Run `tests/test_paths.py tests/test_pdf_agent.py tests/test_skill_registry.py`: PASS.

### Task 2: `pdf_create.py`

**Files:**
- Create: `.codewhale/skills/PDF_Editor/pdf_create.py`
- Test: `tests/test_pdf_create.py`

**Interfaces:**
- `CSP: str`; `PREVIEW_SCALE = 1.5`; `RENDER_TIMEOUT = 60`.
- `sanitize(html: str, resolve_src: Callable[[str], str|None]) -> tuple[str, list[str]]` — strip `<meta http-equiv=refresh>`, `<base>`, `<script>…</script>`; `<img>` src + CSS `url()` resolved via `resolve_src` (returns data-rel path or None) then inlined `data:<mime>;base64,`; `data:` URIs kept; fail → img tag removed / `url(none)`… (`url("")`) + warning naming src. Inject `<meta charset="utf-8">` + CSP meta right after `<head…>`; no head → insert `<head>…</head>` after `<html…>` or after doctype, else prepend.
- `find_browser(configured: str = "") -> str | None` — configured path if file exists; else probe Edge x86/x64, Chrome, `shutil.which` of `msedge`/`chrome`/`chromium`/`google-chrome`.
- `render(html: str, out_pdf: Path, browser: str, timeout: int = RENDER_TIMEOUT) -> None` — temp dir (html + profile), run flags above, kill on timeout, raise `RuntimeError` (timeout / no output); always rmtree temp.
- `preview(pdf: Path, png: Path) -> bool` — page 0 via pypdfium2; False if lib missing.
- `safe_title(title: str) -> str` — strip `\/:*?"<>|` + control chars, trim, cap 60, default `"document"`.
- `new_session_id() -> str`; `session_dir(member, sid) -> Path` (ValueError on bad id).

- [ ] Tests (fake `resolve_src`): `test_csp_injected_into_head`, `test_fragment_gets_head_with_csp` (`"<p>x</p>"` → output contains CSP before `<p>`), `test_remote_and_file_images_removed_with_warning` (https + `file:///C:/x.png` → no `<img`, 2 warnings), `test_local_image_inlined` (png bytes → `src="data:image/png;base64,`), `test_css_url_inlined`, `test_meta_refresh_base_script_stripped`, `test_safe_title` (`'a/b:c?'`→`'abc'`, `''`→`'document'`), `test_session_dir_rejects_bad_id`.
- [ ] Test `test_render_real_browser` (find_browser required; assert pdf starts `%PDF`, pypdfium2 text contains `你好`, `preview()` writes PNG).
- [ ] Test `test_render_timeout_kills` (monkeypatch `subprocess.Popen` stub whose `wait` raises `TimeoutExpired`, assert kill called, RuntimeError, temp removed).
- [ ] Run: FAIL. Implement. Run `tests/test_pdf_create.py`: PASS.

### Task 3: CLI + manifest + config + docs

**Files:**
- Modify: `.codewhale/skills/PDF_Editor/cli.py` (`cmd_create`, parser `pdf-create`: `--html-file` req, `--title`, `--session`, `--member` req)
- Modify: `.codewhale/skills/PDF_Editor/agent_tools.py`
- Modify: `config.json` (`"pdf": {"_comment", "browser": ""}`), `FAM.md` (PDF Editor row + config table), `.codewhale/skills/PDF_Editor/SKILL.md` (code table, session, pitfalls: temp profile, meta refresh, header flag), `README.md:290` tree
- Test: `tests/test_pdf_cli.py`, `tests/test_pdf_agent.py`

**Interfaces:**
- CLI: reads html file (utf-8); `session` valid + exists → reuse dir, else new id (+ `提示:` if given but missing); title default = previous `meta.json` title or `document`; old `*.pdf` in dir removed when title changes; writes `source.html` (raw), `meta.json` `{id,title,created,updated}`, `<title>.pdf`, `preview.png`; `_mark_backup_dirty()`. No browser → `_die("找不到 Edge/Chrome，config.json pdf.browser 填浏览器路径")`.
- Manifest: `create_pdf(args)` callable: html → `tempfile.NamedTemporaryFile(suffix=".html", delete=False)`, `rt.run_cli("pdf-create", {"html-file": tmp, "title", "session", "member"})`, unlink in `finally`. `COMMANDS += pdf-create`, `CLI_TIMEOUTS["pdf-create"] = 90`, `MEMBER_LOCKED`, `DOC_TOOLS += create_pdf`. Not UNTRUSTED (output = own paths).
- Schema `create_pdf(html req, title, session)`; PROMPT_RULE: new doc from scratch (flyer/contract/notice) → `create_pdf`, full self-contained HTML, `@page` size, CJK font stack `"Microsoft YaHei","SimSun",sans-serif`, images only data paths (`<img src="Jim/inbox/…">`), no web URLs/JS, forms = printed lines/boxes; revise = same session + full new HTML; existing PDF → `edit_pdf`.

- [ ] Tests CLI (browser stubbed via monkeypatch `pdf_create.render` writing a 1-page reportlab PDF): `test_create_prints_contract` (line0 `jim/pdf_creates/<sid>/Flyer.pdf`, `预览:` line, `session=`), `test_create_revise_same_session_overwrites`, `test_create_unknown_session_starts_new_with_notice`, `test_create_no_browser_errors`.
- [ ] Tests agent: `create_pdf` in schemas/tool_map/doc_tools/member_locked; `test_create_pdf_passes_html_by_file` (monkeypatch `rt.run_cli` capture args: no `html` key, `html-file` exists during call with 40k-char content, deleted after).
- [ ] Run: FAIL. Implement. Run full suite `conda run -n familyassis310 python -m pytest -q`: PASS.
- [ ] Manual: CLI on real Edge with flyer HTML incl. inbox image; view preview PNG.
