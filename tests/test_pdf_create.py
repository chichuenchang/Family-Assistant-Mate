# tests/test_pdf_create.py — HTML → PDF：清洗（CSP/图片内联/导航剥离）、浏览器渲染、预览。
import base64
import subprocess

import pytest

import pdf_create
from pdf_samples import build_png


def _resolver(tmp_path):
    """假闸门：只认 tmp_path 下 ok/ 开头的相对路径。"""
    def resolve(src):
        p = tmp_path / src
        return str(p) if src.startswith("ok/") and p.is_file() else None
    return resolve


def test_csp_injected_into_head(tmp_path):
    out, warns = pdf_create.sanitize("<!doctype html><html><head><title>t</title></head>"
                                     "<body>x</body></html>", _resolver(tmp_path))
    head = out.split("</head>")[0]
    assert pdf_create.CSP in head and head.index(pdf_create.CSP) < head.index("<title>")
    assert out.startswith("<!doctype html>") and warns == []


def test_fragment_gets_head_with_csp(tmp_path):
    out, _ = pdf_create.sanitize("<p>x</p>", _resolver(tmp_path))
    assert pdf_create.CSP in out and out.index(pdf_create.CSP) < out.index("<p>")
    assert 'charset="utf-8"' in out


def test_remote_and_file_images_removed_with_warning(tmp_path):
    html = ('<body><img src="https://evil.example/a.png" alt="a">'
            "<IMG SRC='file:///C:/secret.png'><img src=\"Other/inbox/x.png\"></body>")
    out, warns = pdf_create.sanitize(html, _resolver(tmp_path))
    assert "<img" not in out.lower()
    assert len(warns) == 3 and "evil.example" in warns[0]


def test_local_image_inlined(tmp_path):
    (tmp_path / "ok").mkdir()
    png = build_png(tmp_path / "ok" / "a.png")
    out, warns = pdf_create.sanitize('<img src="ok/a.png" style="width:3cm">', _resolver(tmp_path))
    b64 = base64.b64encode(png.read_bytes()).decode()
    assert f'src="data:image/png;base64,{b64}"' in out and 'style="width:3cm"' in out
    assert warns == []


def test_data_uri_image_kept(tmp_path):
    out, warns = pdf_create.sanitize('<img src="data:image/png;base64,AAAA">', _resolver(tmp_path))
    assert 'src="data:image/png;base64,AAAA"' in out and warns == []


def test_css_url_inlined_or_blanked(tmp_path):
    (tmp_path / "ok").mkdir()
    build_png(tmp_path / "ok" / "bg.png")
    html = ("<style>.a{background:url('ok/bg.png') no-repeat}"
            ".b{background:url(https://evil.example/x.png)}</style>")
    out, warns = pdf_create.sanitize(html, _resolver(tmp_path))
    assert "url(data:image/png;base64," in out and "evil.example" not in out
    assert len(warns) == 1


def test_url_rewrite_only_in_css(tmp_path):
    (tmp_path / "ok").mkdir()
    build_png(tmp_path / "ok" / "bg.png")
    html = ('<p>call url(foo) now</p><svg><rect fill="url(#g)"/></svg>'
            '<style>.m{mask:url(#m)}</style><div style="background:url(\'ok/bg.png\')">d</div>'
            "<img src='data:image/svg+xml,<svg xmlns=\"x\"/>'>")
    out, warns = pdf_create.sanitize(html, _resolver(tmp_path))
    assert "<p>call url(foo) now</p>" in out and 'fill="url(#g)"' in out and "url(#m)" in out
    assert 'style="background:url(data:image/png;base64,' in out
    assert "<img src='data:image/svg+xml,<svg xmlns=\"x\"/>'>" in out
    assert warns == []


def test_meta_refresh_base_script_stripped(tmp_path):
    html = ('<head><meta http-equiv="refresh" content="0;url=file:///C:/x.txt">'
            '<base href="file:///C:/"><script>alert(1)</script></head><body>'
            '<SCRIPT type="x">bad()</SCRIPT>ok</body>')
    out, _ = pdf_create.sanitize(html, _resolver(tmp_path))
    low = out.lower()
    assert "refresh" not in low and "<base" not in low and "<script" not in low
    assert "ok" in out


def test_csp_first_even_with_decoy_head(tmp_path):
    html = ('<!-- <head> --><html lang="zh"><head><title><head></title></head>'
            '<body>x</body></html>')
    out, _ = pdf_create.sanitize(html, _resolver(tmp_path))
    csp = out.index(pdf_create.CSP)
    assert csp < out.index("<!--") and csp < out.index("<title>")
    assert out.startswith('<!doctype html><html lang="zh"><head>')


@pytest.mark.parametrize("tag", [
    '<meta content="0;url=file:///C:/x.txt" data-x=">" http-equiv="refresh">',   # 引号内 >
    "<meta x=a' http-equiv=refresh content=\"0;url=file:///C:/x.txt\">",       # 未配对引号
    "<BASE x=a' href=\"file:///C:/\">",
    '<meta name="viewport" content="width=device-width">',
])
def test_every_meta_and_base_neutralized(tmp_path, tag):
    out, _ = pdf_create.sanitize(f"<head>{tag}</head><p>x</p><meta-card>ok</meta-card>",
                                 _resolver(tmp_path))
    low = out.lower()
    assert low.count("<meta ") == 2 and "<meta-card>" in low     # 只剩自注入 charset + CSP
    assert "<base" not in low


def test_html_attr_quote_cannot_swallow_csp(tmp_path):
    out, _ = pdf_create.sanitize("<html lang='zh\"><b' x='>'><p>y</p>", _resolver(tmp_path))
    assert out.startswith('<!doctype html><html lang="zh&quot;&gt;&lt;b"><head><meta charset')
    assert out.index(pdf_create.CSP) < out.index("<p>")


def test_bom_dropped(tmp_path):
    out, _ = pdf_create.sanitize("﻿<!doctype html><p>x</p>", _resolver(tmp_path))
    assert "﻿" not in out


def test_any_http_equiv_meta_stripped(tmp_path):
    html = '<head><meta http-equiv="&#114;efresh" content="0;url=file:///C:/x.txt"></head>'
    out, _ = pdf_create.sanitize(html, _resolver(tmp_path))
    assert "file:///" not in out


def test_safe_title():
    assert pdf_create.safe_title('a/b:c?"<>|*\\d') == "abcd"
    assert pdf_create.safe_title("   ") == "document"
    assert pdf_create.safe_title("租约 2026") == "租约 2026"
    assert len(pdf_create.safe_title("x" * 200)) == 60


def test_session_dir_rejects_bad_id(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path / "data"))
    with pytest.raises(ValueError):
        pdf_create.session_dir("jim", "../evil")
    sid = pdf_create.pdf_plan.new_session_id()
    assert pdf_create.session_dir("jim", sid).as_posix().endswith(f"jim/pdf_creates/{sid}")


def test_find_browser_prefers_configured(tmp_path):
    exe = tmp_path / "b.exe"
    exe.write_bytes(b"")
    assert pdf_create.find_browser(str(exe)) == str(exe)


def test_render_real_browser(tmp_path):
    pypdfium2 = pytest.importorskip("pypdfium2")
    browser = pdf_create.find_browser()
    assert browser, "需 Edge/Chrome（familyassis310 机器上有）"
    html, _ = pdf_create.sanitize("<style>@page{size:A4}</style><h1>你好 Flyer</h1>",
                                  lambda s: None)
    out = tmp_path / "o.pdf"
    pdf_create.render(html, out, browser)
    assert out.read_bytes()[:4] == b"%PDF"
    doc = pypdfium2.PdfDocument(str(out))
    assert "你好" in doc[0].get_textpage().get_text_range()
    doc.close()
    png = tmp_path / "p.png"
    assert pdf_create.preview(out, png) and png.read_bytes()[:4] == b"\x89PNG"


def test_render_cannot_read_local_file(tmp_path):
    """端到端：CSP 被吞时 iframe 能把本机文件印进 PDF。"""
    pypdfium2 = pytest.importorskip("pypdfium2")
    secret = tmp_path / "secret.txt"
    secret.write_text("TOPSECRET42", encoding="utf-8")
    html, _ = pdf_create.sanitize(f"<html x='>'><iframe src=\"{secret.as_uri()}\"></iframe>"
                                  "<p>visible</p>", lambda s: None)
    out = tmp_path / "o.pdf"
    pdf_create.render(html, out, pdf_create.find_browser())
    doc = pypdfium2.PdfDocument(str(out))
    text = doc[0].get_textpage().get_text_range()
    doc.close()
    assert "visible" in text and "TOPSECRET42" not in text


def test_render_timeout_kills(tmp_path, monkeypatch):
    seen = {}

    class FakeProc:
        def __init__(self, argv, **kw):
            seen["argv"] = argv
            seen["tmp"] = next(a.split("=", 1)[1] for a in argv if a.startswith("--user-data-dir="))
            self.killed = False

        def wait(self, timeout=None):
            if not self.killed:
                raise subprocess.TimeoutExpired("b", timeout)
            return -9

        def kill(self):
            self.killed = True
            seen["killed"] = True

    monkeypatch.setattr(pdf_create.subprocess, "Popen", FakeProc)
    with pytest.raises(RuntimeError):
        pdf_create.render("<p>x</p>", tmp_path / "o.pdf", "browser.exe", timeout=1)
    assert seen["killed"]
    assert "--no-pdf-header-footer" in seen["argv"] and "--headless" in seen["argv"]
    import os
    assert not os.path.exists(seen["tmp"])
