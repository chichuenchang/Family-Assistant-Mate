# tests/test_browser_live.py — 真 Chrome + Playwright 驱动冒烟（缺 playwright 或 Chrome 自动跳过）
# 会在桌面弹出一个 Chrome 窗口，跑完自动关。
import functools
import http.server
import importlib.util
import random
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import pytest

import browser_chrome as bc

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("playwright") is None or not bc.find_chrome(),
    reason="需 playwright + Chrome")

PAGE = """<!doctype html><html><head><meta charset=utf-8><title>t</title></head><body>
<button onclick="document.title='clicked'">Go</button>
<input type=text name=q placeholder="search">
<input type=password name=pw>
<a href="/other.html" target=_blank>Open</a>
<div style="height:2500px"></div>
<button onclick="document.title='far'">Far</button>
<img src="/big.png" alt="cat" width=300 height=300>
<script>window.moves=[];addEventListener('mousemove',e=>moves.push({trusted:e.isTrusted}))</script>
</body></html>"""


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def site():
    root = Path(tempfile.mkdtemp(prefix="fam_site_"))
    (root / "index.html").write_text(PAGE, encoding="utf-8")
    (root / "other.html").write_text("<title>other</title>other", encoding="utf-8")
    from PIL import Image
    Image.new("RGB", (300, 300), (200, 30, 30)).save(root / "big.png")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/index.html"
    srv.shutdown()


@pytest.fixture(scope="module")
def driver():
    import browser_playwright as bp
    port = _free_port()
    proc = subprocess.Popen(bc.launch_argv(bc.find_chrome(), Path(tempfile.mkdtemp(prefix="fam_prof_")), port))
    for _ in range(30):
        if bc.is_up(port):
            break
        time.sleep(0.5)
    # 测试站在 127.0.0.1：放开图片地址检查；默认检查另测
    d = bp.PlaywrightDriver(bc.endpoint(port), rng=random.Random(1), speed=5, url_check=lambda u: "")
    yield d
    d.close()
    bp.quit(bc.endpoint(port))
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture
def drv(driver, site):
    while len(driver.tabs()) > 1:
        driver.close_tab(len(driver.tabs()) - 1)
    driver.switch_tab(0)
    driver.navigate(site)
    return driver


def ref_of(drv, role, label=None):
    return next(e.ref for e in drv.snapshot().elements
                if e.role == role and (label is None or e.label == label))


def test_snapshot_lists_refs(drv):
    s = drv.snapshot()
    assert {"button", "textbox", "link", "image"} <= {e.role for e in s.elements}
    assert s.title == "t" and s.url.endswith("/index.html")


def test_password_field_flagged(drv):
    assert any(e.input_type == "password" for e in drv.snapshot().elements)


def test_click_moves_like_a_hand(drv):
    drv.click(ref_of(drv, "button", "Go"))
    assert drv.snapshot().title == "clicked"
    moves = drv._page.evaluate("window.moves")
    assert len(moves) > 5 and all(m["trusted"] for m in moves)


def test_click_offscreen_scrolls_first(drv):
    drv.click(ref_of(drv, "button", "Far"))
    assert drv.snapshot().title == "far"


def test_type_fills_field(drv):
    drv.type(ref_of(drv, "textbox"), "hello")
    assert drv._page.evaluate("document.querySelector('input[name=q]').value") == "hello"


def test_type_replaces_existing_text(drv):
    ref = ref_of(drv, "textbox")
    drv.type(ref, "first")
    drv.type(ref, "second")
    assert drv._page.evaluate("document.querySelector('input[name=q]').value") == "second"


def test_focused_reports_button(drv):
    drv._page.focus("button")
    f = drv.focused()
    assert f is not None and (f.role, f.label) == ("button", "Go")


def test_focused_descends_into_iframe(drv):
    drv._page.set_content('<iframe srcdoc="<button>Buy Now</button>"></iframe>')
    drv._page.frames[1].wait_for_selector("button")
    drv._page.frames[1].focus("button")
    f = drv.focused()
    assert f is not None and f.label == "Buy Now"


def test_focused_none_on_body(drv):
    assert drv.focused() is None


def test_not_flagged_as_automation(drv):
    assert drv._page.evaluate("navigator.webdriver") is False


def test_stale_ref_is_recoverable(drv):
    import browser_driver as bd
    with pytest.raises(bd.DriverError):
        drv.click("e999")


def test_screenshot_png(drv, tmp_path):
    p = tmp_path / "s.png"
    drv.screenshot(p)
    assert p.read_bytes()[:4] == b"\x89PNG"


def test_screenshot_works_when_window_minimized(drv, tmp_path):
    bs = drv._browser.new_browser_cdp_session()
    tid = drv._ctx.new_cdp_session(drv._page).send("Target.getTargetInfo")["targetInfo"]["targetId"]
    wid = bs.send("Browser.getWindowForTarget", {"targetId": tid})["windowId"]
    bs.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": "minimized"}})
    drv._page.wait_for_timeout(500)
    p = tmp_path / "m.png"
    drv.screenshot(p)
    assert p.read_bytes()[:4] == b"\x89PNG"


def test_fetch_image(drv, tmp_path):
    assert drv.fetch_image(ref_of(drv, "image"), tmp_path).suffix == ".png"


def test_fetch_image_refuses_local_network_src(drv, tmp_path, monkeypatch):
    import browser_driver as bd
    import browser_guard
    monkeypatch.setattr(drv, "_url_check", browser_guard.check_navigate)
    with pytest.raises(bd.DriverError, match="本机或局域网"):
        drv.fetch_image(ref_of(drv, "image"), tmp_path)
    assert not list(tmp_path.iterdir())


def test_new_tab_followed(drv):
    drv.click(ref_of(drv, "link"))
    assert len(drv.tabs()) == 2 and drv.url().endswith("/other.html")


def test_local_file_url_blocked_is_guard_job_not_driver(drv, site):
    drv.navigate(site.replace("index", "other"))
    assert drv.snapshot().title == "other"
