"""Playwright 实现的 Driver：经调试端口挂到 FAM 自己启动的可见 Chrome（connect_over_cdp）。

- 输入全走 page.mouse / page.keyboard（CDP 真实输入事件，isTrusted），路径与节奏来自 browser_humanize；
  从不用 locator.click()（光标瞬移）。
- 同步 API 对象绑定创建线程：只在浏览任务线程里构造、使用。
- 窗口最小化时截图会卡到超时（实测 Chrome 156）：挂上时与每次截图前先把窗口恢复成 normal。
- close() 只断开，Chrome 留着给下一个任务；真关 Chrome 用 quit()。
"""

from __future__ import annotations

import base64
import functools
import io
import random
import time
import uuid
from pathlib import Path

from playwright.sync_api import Error as PwError
from playwright.sync_api import TimeoutError as PwTimeout
from playwright.sync_api import sync_playwright

import browser_guard
import browser_humanize as hz
from browser_driver import LABEL_CAP, MAX_ELEMENTS, TEXT_CAP, DriverError, DriverGone, Element, Snapshot

NAV_TIMEOUT_MS = 30_000
ACTION_TIMEOUT_MS = 10_000
IMG_MAX_BYTES = 5 * 1024 * 1024

# 给每个可交互元素打 data-fam-ref；视口内的优先，总数封顶。args = [起始编号, 上限, 标签长度]
_TAG_JS = r"""
([start, cap, labelCap]) => {
  const SEL = 'a[href],button,input,select,textarea,summary,[role=button],[role=link],[role=tab],' +
    '[role=menuitem],[role=option],[role=checkbox],[role=radio],[role=combobox],[role=textbox],' +
    '[onclick],[contenteditable=""],[contenteditable=true],img';
  document.querySelectorAll('[data-fam-ref]').forEach(e => e.removeAttribute('data-fam-ref'));
  const vh = innerHeight, vw = innerWidth, cand = [];
  for (const el of document.querySelectorAll(SEL)) {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    const st = getComputedStyle(el);
    if (st.visibility === 'hidden' || st.display === 'none' || st.opacity === '0') continue;
    const tag = el.tagName.toLowerCase();
    if (tag === 'img' && (r.width < 100 || r.height < 100)) continue;
    if (tag === 'input' && el.type === 'hidden') continue;
    const inView = r.bottom > 0 && r.top < vh && r.right > 0 && r.left < vw;
    cand.push([inView ? 0 : 1, cand.length, el]);
  }
  cand.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const picked = cand.slice(0, cap).sort((a, b) => a[1] - b[1]);
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  const out = []; let n = start;
  for (const [, , el] of picked) {
    const tag = el.tagName.toLowerCase(), type = (el.type || '').toLowerCase();
    let role = el.getAttribute('role') || '';
    if (!role) {
      if (tag === 'a') role = 'link';
      else if (tag === 'img') role = 'image';
      else if (tag === 'select') role = 'combobox';
      else if (tag === 'textarea' || el.isContentEditable) role = 'textbox';
      else if (tag === 'input') role = ['checkbox', 'radio'].includes(type) ? type
        : ['submit', 'button', 'reset', 'image'].includes(type) ? 'button' : 'textbox';
      else role = 'button';
    }
    const label = tag === 'img' ? clean(el.alt || el.title)
      : clean(el.innerText) || clean(el.getAttribute('aria-label')) || clean(el.placeholder)
        || clean(el.title) || (type === 'password' ? '' : clean(el.value));
    n += 1;
    el.setAttribute('data-fam-ref', 'e' + n);
    out.push({ref: 'e' + n, role, label: label.slice(0, labelCap), input_type: tag === 'input' ? type : '',
              autocomplete: el.getAttribute('autocomplete') || '', name: el.name || el.id || '',
              href: tag === 'a' ? el.href : ''});
  }
  return {items: out, next: n};
}
"""

_MAGIC = [(b"\xff\xd8\xff", ".jpg"), (b"\x89PNG", ".png"), (b"GIF8", ".gif")]


def _guard(fn):
    """Playwright 异常 → DriverGone（浏览器没了）/ DriverError（其余，可恢复）。"""
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except DriverError:
            raise
        except PwTimeout as e:
            raise DriverError(f"超时：{str(e).splitlines()[0][:150]}") from e
        except PwError as e:
            msg = str(e)
            if "closed" in msg.lower() or "disconnected" in msg.lower():
                raise DriverGone("浏览器已关闭或连接中断") from e
            raise DriverError(msg.splitlines()[0][:200]) from e
    return wrapper


class PlaywrightDriver:
    def __init__(self, endpoint: str, *, humanize: bool = True, speed: float = 1.0,
                 rng: random.Random | None = None, url_check=browser_guard.check_navigate):
        self._url_check = url_check      # 图片地址由网页决定：下载前同导航一样查（防探本机/局域网）
        self._humanize = humanize
        self._speed = max(float(speed), 0.1)
        self._rng = rng or random.Random()
        self._pw = sync_playwright().start()
        try:
            self._browser = self._pw.chromium.connect_over_cdp(endpoint)
        except Exception as e:
            self._pw.stop()
            raise DriverGone(f"连不上浏览器：{e}") from e
        self._ctx = (self._browser.contexts or [self._browser.new_context()])[0]
        self._ctx.set_default_timeout(ACTION_TIMEOUT_MS)
        self._ctx.on("page", self._watch)
        for p in self._ctx.pages:
            self._watch(p)
        self._page = self._ctx.pages[-1] if self._ctx.pages else self._ctx.new_page()
        self._refs: dict[str, object] = {}     # ref → 所在 frame
        self._pos: tuple[float, float] | None = None
        self._restore_window()

    # ── 内部 ────────────────────────────────────────────
    @staticmethod
    def _watch(page) -> None:
        page.on("dialog", lambda d: d.dismiss())

    def _wait(self, s: float) -> None:
        """等待且让 Playwright 处理事件（新标签、弹窗）；time.sleep 不处理，新标签会看不到。"""
        self._page.wait_for_timeout(s * 1000)

    def _sleep(self, s: float) -> None:
        if self._humanize and s > 0:
            self._wait(s / self._speed)

    def _pause(self) -> None:
        self._sleep(hz.think_pause(self._rng))

    def _restore_window(self) -> None:
        try:
            cdp = self._ctx.new_cdp_session(self._page)
            tid = cdp.send("Target.getTargetInfo")["targetInfo"]["targetId"]
            cdp.detach()
            bs = self._browser.new_browser_cdp_session()
            wid = bs.send("Browser.getWindowForTarget", {"targetId": tid})["windowId"]
            if bs.send("Browser.getWindowBounds", {"windowId": wid})["bounds"].get("windowState") == "minimized":
                bs.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": "normal"}})
                time.sleep(0.3)
            bs.detach()
        except PwError:
            pass

    def _viewport(self) -> tuple[float, float]:
        w, h = self._page.evaluate("[innerWidth, innerHeight]")
        return float(w), float(h)

    def _settle(self) -> None:
        try:
            self._page.wait_for_load_state("domcontentloaded", timeout=NAV_TIMEOUT_MS)
            self._page.wait_for_load_state("networkidle", timeout=3000)
        except PwTimeout:
            pass

    def _locator(self, ref: str):
        frame = self._refs.get(ref)
        if frame is None:
            raise DriverError("ref 已失效，先 read_page")
        return frame.locator(f'[data-fam-ref="{ref}"]').first

    def _move_to(self, x: float, y: float) -> None:
        start = self._pos or self._viewport_center()
        path = hz.mouse_path(start, (x, y), self._rng) if self._humanize else [(x, y, 0.0)]
        for px, py, s in path:
            self._page.mouse.move(px, py)
            self._sleep(s)
        self._pos = (x, y)

    def _viewport_center(self) -> tuple[float, float]:
        w, h = self._viewport()
        return w / 2, h / 2

    def _wheel(self, pixels: int) -> None:
        if self._pos is None:
            self._move_to(*self._viewport_center())
        steps = hz.scroll_steps(pixels, self._rng) if self._humanize else [(pixels, 0.0)]
        for delta, s in steps:
            self._page.mouse.wheel(0, delta)
            self._sleep(s)
        self._wait(0.15)   # 让滚动落定再量位置

    def _box_in_view(self, loc) -> tuple[float, float, float, float]:
        for _ in range(4):
            box = loc.bounding_box()
            if box is None:
                raise DriverError("元素不可见（可能已被移除），先 read_page")
            _, vh = self._viewport()
            mid = box["y"] + box["height"] / 2
            if 0 <= box["y"] and box["y"] + box["height"] <= vh or 0 < mid < vh:
                return box["x"], box["y"], box["width"], box["height"]
            self._wheel(int(mid - vh / 2))
        loc.scroll_into_view_if_needed()
        box = loc.bounding_box()
        if box is None:
            raise DriverError("元素不可见，先 read_page")
        return box["x"], box["y"], box["width"], box["height"]

    def _press_at(self, box) -> None:
        x, y = hz.target_point(box, self._rng)
        self._move_to(x, y)
        dwell, hold = hz.click_delays(self._rng)
        self._sleep(dwell)
        self._page.mouse.down()
        self._sleep(hold)
        self._page.mouse.up()

    # ── Driver ──────────────────────────────────────────
    @_guard
    def navigate(self, url: str) -> None:
        self._page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        self._settle()
        self._refs.clear()
        self._pause()

    @_guard
    def snapshot(self) -> Snapshot:
        self._refs.clear()
        elements: list[Element] = []
        n = 0
        for frame in self._page.frames:
            if len(elements) >= MAX_ELEMENTS:
                break
            try:
                res = frame.evaluate(_TAG_JS, [n, MAX_ELEMENTS - len(elements), LABEL_CAP])
            except PwError:
                continue      # 跨域/已卸载的 frame
            n = res["next"]
            for item in res["items"]:
                self._refs[item["ref"]] = frame
                elements.append(Element(**item))
        text = self._page.evaluate("document.body ? document.body.innerText : ''") or ""
        text = "\n".join(ln.strip() for ln in text.splitlines() if ln.strip())
        return Snapshot(self._page.url, self._page.title(), text[:TEXT_CAP], elements)

    @_guard
    def click(self, ref: str) -> None:
        loc = self._locator(ref)
        before = len(self._ctx.pages)
        self._press_at(self._box_in_view(loc))
        self._wait(0.5)
        if len(self._ctx.pages) > before:          # target=_blank：跟到新标签
            self._page = self._ctx.pages[-1]
            self._page.bring_to_front()
            self._pos = None
        self._settle()
        self._pause()

    @_guard
    def type(self, ref: str, text: str, submit: bool = False) -> None:
        loc = self._locator(ref)
        self._press_at(self._box_in_view(loc))
        self._page.keyboard.press("Control+A")
        self._page.keyboard.press("Delete")
        if self._humanize:
            for ch, d in zip(text, hz.key_delays(text, self._rng)):
                self._page.keyboard.type(ch)
                self._sleep(d)
        else:
            self._page.keyboard.type(text)
        if submit:
            self._page.keyboard.press("Enter")
            self._settle()
        self._pause()

    @_guard
    def press(self, key: str) -> None:
        self._page.keyboard.press(key)
        self._settle()
        self._pause()

    @_guard
    def scroll(self, pixels: int) -> None:
        self._wheel(int(pixels))
        self._pause()

    @_guard
    def back(self) -> None:
        self._page.go_back(wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        self._settle()
        self._refs.clear()

    @_guard
    def tabs(self) -> list[tuple[int, str, str]]:
        return [(i, p.title(), p.url) for i, p in enumerate(self._ctx.pages)]

    @_guard
    def switch_tab(self, index: int) -> None:
        pages = self._ctx.pages
        if not 0 <= index < len(pages):
            raise DriverError(f"没有第 {index} 个标签页")
        self._page = pages[index]
        self._page.bring_to_front()
        self._refs.clear()
        self._pos = None

    @_guard
    def close_tab(self, index: int) -> None:
        pages = self._ctx.pages
        if len(pages) <= 1:
            raise DriverError("只剩一个标签页，不能关")
        if not 0 <= index < len(pages):
            raise DriverError(f"没有第 {index} 个标签页")
        closing = pages[index]
        closing.close()
        if closing is self._page:
            self._page = self._ctx.pages[-1]
            self._refs.clear()
            self._pos = None

    @_guard
    def screenshot(self, path: Path) -> None:
        self._restore_window()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._page.screenshot(path=str(path), timeout=15_000)

    @_guard
    def fetch_image(self, ref: str, dest_dir: Path) -> Path:
        src = self._locator(ref).evaluate("e => e.currentSrc || e.src || ''")
        if not src:
            raise DriverError("这个元素不是图片")
        if src.startswith("data:"):
            data = base64.b64decode(src.split(",", 1)[1])
        else:
            reason = self._url_check(src)
            if reason:
                raise DriverError(f"不下载这张图：{reason}")
            resp = self._ctx.request.get(src, timeout=15_000)
            if not resp.ok:
                raise DriverError(f"图片下载失败 HTTP {resp.status}")
            data = resp.body()
        if len(data) > IMG_MAX_BYTES:
            raise DriverError("图片超过 5 MB")
        ext = next((e for magic, e in _MAGIC if data.startswith(magic)), None)
        if ext is None:
            data, ext = _to_png(data), ".png"
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        out = dest / f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}{ext}"
        out.write_bytes(data)
        return out

    def url(self) -> str:
        try:
            return self._page.url
        except PwError:
            return ""

    def close(self) -> None:
        try:
            self._pw.stop()
        except Exception:
            pass


def _to_png(data: bytes) -> bytes:
    """webp/avif 等微信发不了的格式转 PNG；转不了 → DriverError。"""
    try:
        from PIL import Image
        buf = io.BytesIO()
        Image.open(io.BytesIO(data)).save(buf, "PNG")
        return buf.getvalue()
    except Exception as e:
        raise DriverError("图片格式不支持（只收 jpg/png/gif，webp 需 Pillow）") from e


def quit(endpoint: str) -> None:
    """挂上并让 Chrome 自己退出（Browser.close）。"""
    pw = sync_playwright().start()
    try:
        b = pw.chromium.connect_over_cdp(endpoint)
        b.new_browser_cdp_session().send("Browser.close")
    finally:
        pw.stop()
