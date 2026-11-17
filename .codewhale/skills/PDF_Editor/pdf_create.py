"""
FAM — 从零生成 PDF（PDF_Editor）：Agent 写的 HTML/CSS → 无头 Edge/Chrome 打印成 PDF。

HTML 可能转述邮件/网页等外部文本 → 渲染前清洗：注入 CSP（无脚本、无网络、无本地文件读取），
剥掉 CSP 管不到的导航（meta refresh / base），图片只认闸门放行的 data 路径并内联为 data: URI。
设计：docs/superpowers/specs/2026-11-17-pdf-create-design.md。
"""

from __future__ import annotations

import base64
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Callable

import paths as _paths

CSP = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; font-src data:"
PREVIEW_SCALE = 1.5          # A4 → 约 890×1260 px，聊天里看得清
RENDER_TIMEOUT = 60
TITLE_MAX = 60
_ID_RE = re.compile(r"[0-9]{8}_[0-9]{6}_[0-9a-f]{4}")   # 同 pdf_plan 会话 id

_HEAD_META = (f'<meta charset="utf-8">'
              f'<meta http-equiv="Content-Security-Policy" content="{CSP}">')
_SCRIPT_RE = re.compile(r"<script\b.*?(?:</script\s*>|$)", re.I | re.S)
# 一切 http-equiv 都剥：值可用实体编码（&#114;efresh）绕过按值匹配；CSP 由我们自己注入
_HTTP_EQUIV_RE = re.compile(r"<meta\b[^>]*http-equiv[^>]*>", re.I)
_ATTRS = r"""(?:"[^"]*"|'[^']*'|[^'">])*"""     # 标签体：引号里的 > 不结束标签
_SHELL_RE = re.compile(rf"<!doctype[^>]*>|<(?:html|head)(?=[\s/>]){_ATTRS}>", re.I)
_HTML_TAG_RE = re.compile(rf"<html(?=[\s/>]){_ATTRS}>", re.I)
_KEEP_ATTR_RE = re.compile(r"""\b(lang|dir)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>"']+))""", re.I)
_BASE_RE = re.compile(r"<base\b[^>]*>", re.I)
_IMG_RE = re.compile(r"<img\b[^>]*>", re.I)
_SRC_RE = re.compile(r"""\bsrc\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.I)
_SRCSET_RE = re.compile(r"""\s\bsrcset\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)""", re.I)
_URL_RE = re.compile(r"""url\(\s*(?:"([^"]*)"|'([^']*)'|([^)'"]*?))\s*\)""", re.I)
_TITLE_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]')

_BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]
_BROWSER_NAMES = ("msedge", "microsoft-edge", "chrome", "google-chrome", "chromium", "chromium-browser")


# ── 清洗 ─────────────────────────────────────────────────────

def _data_uri(src: str, resolve_src: Callable[[str], str | None]) -> str | None:
    """data: 原样；否则闸门放行且是图片 → base64 data URI；其余 None。"""
    if src.lower().startswith("data:"):
        return src
    p = resolve_src(src)
    if not p:
        return None
    mime = mimetypes.guess_type(p)[0] or ""
    if not mime.startswith("image/"):
        return None
    return f"data:{mime};base64," + base64.b64encode(Path(p).read_bytes()).decode()


def sanitize(html: str, resolve_src: Callable[[str], str | None]) -> tuple[str, list[str]]:
    """→ (可交给浏览器的 HTML, 警告)。resolve_src(路径) → 本地文件路径或 None（成员闸门）。"""
    warns: list[str] = []
    html = html.replace("﻿", "")    # 壳重建后 BOM 落进 head 成文本 → 页顶白条
    html = _SCRIPT_RE.sub("", html)
    html = _HTTP_EQUIV_RE.sub("", html)
    html = _BASE_RE.sub("", html)

    def img(m):
        tag = _SRCSET_RE.sub("", m.group(0))
        sm = _SRC_RE.search(tag)
        src = next((g for g in sm.groups() if g is not None), "") if sm else ""
        uri = _data_uri(src, resolve_src) if src else None
        if uri is None:
            warns.append(f"图片已去掉（只能用 data 内自己/家庭的图片路径）: {src[:80] or '(无 src)'}")
            return ""
        return tag[:sm.start()] + f'src="{uri}"' + tag[sm.end():]

    def url(m):
        src = next(g for g in m.groups() if g is not None).strip()
        uri = _data_uri(src, resolve_src) if src else None
        if uri is None:
            if src:
                warns.append(f"CSS 图片已去掉: {src[:80]}")
            return 'url("")'
        return f'url("{uri}")'

    html = _IMG_RE.sub(img, html)
    html = _URL_RE.sub(url, html)
    return _inject_head(html), warns


def _inject_head(html: str) -> str:
    """重建文档壳，CSP 恒为第一个 head 子元素。不找原 <head> 插：注释/<title> 里的假 <head>
    会把 CSP 骗进文本里失效。原 <html> 只留 lang/dir（lang 影响 CJK 字形），转义重写：
    原样搬属性则 <html x='> 的引号把 CSP 吞进属性值（实测 iframe 读出本机文件）。"""
    keep: dict[str, str] = {}
    if m := _HTML_TAG_RE.search(html):
        for a in _KEEP_ATTR_RE.finditer(m.group(0)):
            keep.setdefault(a.group(1).lower(), next(g for g in a.groups()[1:] if g is not None))
    attrs = "".join(f' {k}="{escape(v, quote=True)}"' for k, v in keep.items())
    return f"<!doctype html><html{attrs}><head>{_HEAD_META}" + _SHELL_RE.sub("", html)


# ── 渲染 ─────────────────────────────────────────────────────

def find_browser(configured: str = "") -> str | None:
    if configured and Path(configured).is_file():
        return configured
    for p in _BROWSERS:
        if Path(p).is_file():
            return p
    for n in _BROWSER_NAMES:
        found = shutil.which(n)
        if found:
            return found
    return None


def render(html: str, out_pdf: Path, browser: str, timeout: int = RENDER_TIMEOUT) -> None:
    """HTML（已清洗）→ out_pdf。临时目录放页面 + 独立 profile（共用 profile 会把任务
    交给已在跑的浏览器）。超时杀进程；失败抛 RuntimeError。"""
    tmp = Path(tempfile.mkdtemp(prefix="fam_pdf_"))
    try:
        page = tmp / "page.html"
        page.write_text(html, encoding="utf-8")
        tmp_out = tmp / "out.pdf"
        argv = [browser, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                "--no-first-run", "--disable-extensions",
                f"--user-data-dir={tmp / 'profile'}", f"--print-to-pdf={tmp_out}", page.as_uri()]
        proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            raise RuntimeError(f"浏览器渲染超时（{timeout}s）")
        if not tmp_out.is_file() or tmp_out.stat().st_size == 0:
            raise RuntimeError("浏览器没有产出 PDF")
        Path(out_pdf).parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(tmp_out), str(out_pdf))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def preview(pdf: Path, png: Path) -> bool:
    """第 1 页 → PNG。缺 pypdfium2 → False。"""
    try:
        import pypdfium2
    except ImportError:
        return False
    doc = pypdfium2.PdfDocument(str(pdf))
    try:
        doc[0].render(scale=PREVIEW_SCALE).to_pil().save(str(png))
    finally:
        doc.close()
    return True


# ── 会话 ─────────────────────────────────────────────────────

def safe_title(title: str) -> str:
    t = _TITLE_BAD.sub("", title or "").strip()[:TITLE_MAX].rstrip(" .")
    return t or "document"


def new_session_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:4]


def session_dir(member: str, session_id: str) -> Path:
    if not _ID_RE.fullmatch(session_id or ""):
        raise ValueError(f"非法会话 id: {session_id}")
    return _paths.member_pdf_creates_dir(member) / session_id
