# PDF create from scratch

Why: FAM edits existing PDFs only. Need: FAM composes doc (contract, flyer; text, graphics, forms, images), tool turns it into PDF to hand people. Content = FAM's job; tool = renderer only.

## Decided (user)

- Approach A: FAM writes HTML/CSS, headless browser prints PDF.
- User talks via WeChat: cannot view HTML. Sees result as PDF file + page-1 PNG preview in chat.

## Approaches

- **Picked A: HTML/CSS + headless Edge/Chrome `--print-to-pdf`.** LLM fluent in HTML; flyer quality = layout freedom. Edge + Chrome both on bot machine.
- Rejected B: JSON blocks + reportlab. No browser dep, fillable fields; but fixed vocabulary, flyers plain, each layout idea = new block type.
- Rejected C: Markdown. Too weak for flyers.

## Design (Claude's calls)

- Lives in PDF_Editor skill: `pdf_create.py`, CLI `pdf-create`, tool `create_pdf`. Reuses member gate, session pattern, `DOC_TOOLS` contract.
- Args: `html` (full document), `title` (file name), `session` (revise). Revise = full new HTML, same session, overwrite PDF. No HTML diffs.
- Session `data/<member>/pdf_creates/<id>/`: `source.html`, `<title>.pdf`, `preview.png`.
- Images: `<img src>` = data-relative path, each gated by `rt.resolve_sendable`, inlined as `data:` URI. Fail gate → drop + `警告:`.
- Lockdown (HTML may echo untrusted mail/web text): injected CSP `default-src 'none'; img-src data:; style-src 'unsafe-inline'; font-src data:` — no scripts, no network, no file reads. Browser gets temp file only.
- Header/footer: browser default prints URL + date; must disable (`--no-pdf-header-footer`; older flag name differs, verify on installed build).
- Page size/margins: FAM sets `@page`; default A4.
- Fonts: system fonts by CSS name; prompt rule gives CJK-safe stack (`"Microsoft YaHei", SimSun`, …).
- Preview: page 1 via pypdfium2 → PNG, sent as image. pypdfium2 missing → PDF only + `提示:`.
- Browser path: config key, fallback probe of Edge/Chrome default paths. None → `[错误]` naming fix.
- Forms: printable (lines, boxes) only.
- Timeout ~60s.

## Left to builder

- How one tool returns both doc + image (registry: `DOC_TOOLS` first-line path vs `IMAGE_TOOLS`); maybe second output line or tool in both sets.
- Prompt rule wording: when `create_pdf` vs `edit_pdf`; images must be data paths.

## Non-goals

Fillable form fields (later: PDF Editor adds them), remote images/fonts, FAM self-checking render via Vision, multi-page preview.
