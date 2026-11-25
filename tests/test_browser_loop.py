# tests/test_browser_loop.py — 浏览助手内循环：工具派发、拦截、截图、上限、收尾（假驱动 + 脚本化模型）
import copy
import itertools
import json
from pathlib import Path

import pytest

import browser_chrome as bc
import browser_driver as bd
import browser_loop as bl
import tool_runtime as rt

_ids = itertools.count()


def call(name, **args):
    return raw_call(name, json.dumps(args, ensure_ascii=False))


def raw_call(name, arguments):
    return {"id": f"c{next(_ids)}", "type": "function",
            "function": {"name": name, "arguments": arguments}}


class Script:
    """假 chat：按脚本逐条回复；记录每次收到的 messages / tools。"""

    def __init__(self, *turns):
        self.turns = list(turns)
        self.seen, self.tools_seen = [], []

    def __call__(self, messages, tools, model, effort, **kw):
        self.seen.append(copy.deepcopy(messages))
        self.tools_seen.append(tools)
        t = self.turns.pop(0) if self.turns else "（脚本完）"
        if isinstance(t, str):
            return {"role": "assistant", "content": t, "_usage": {}, "_finish": "stop"}
        return {"role": "assistant", "content": "", "tool_calls": t, "_usage": {}}


def script(*turns):
    return Script(*turns)


def el(ref, role, label, **kw):
    return bd.Element(ref, role, label, **kw)


def snap(*elements, url="https://shop.example/item"):
    return bd.Snapshot(url, "页面", "正文", list(elements))


class FakeDriver:
    def __init__(self):
        self.calls = []
        self.snaps = [snap()]
        self.current_url = "https://start.example/"
        self.url_after_click = None
        self.fail_next = None

    def _act(self, *c):
        if self.fail_next:
            e, self.fail_next = self.fail_next, None
            raise e
        self.calls.append(c)

    def navigate(self, url):
        self._act("navigate", url)
        self.current_url = url

    def snapshot(self):
        return self.snaps[0] if len(self.snaps) == 1 else self.snaps.pop(0)

    def click(self, ref):
        self._act("click", ref)
        if self.url_after_click:
            self.current_url = self.url_after_click

    def type(self, ref, text, submit=False):
        self._act("type", ref, text)

    def press(self, key):
        self._act("press", key)

    def scroll(self, pixels):
        self._act("scroll", pixels)

    def back(self):
        self._act("back")

    def tabs(self):
        return [(0, "页面", self.current_url)]

    def switch_tab(self, i):
        self._act("switch_tab", i)

    def close_tab(self, i):
        self._act("close_tab", i)

    def screenshot(self, path):
        self._act("screenshot")
        Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)

    def fetch_image(self, ref, dest_dir):
        self._act("fetch_image", ref)
        p = Path(dest_dir) / "img.jpg"
        p.write_bytes(b"\xff\xd8\xff" + b"0" * 16)
        return p

    def url(self):
        return self.current_url

    def close(self):
        pass


CFG = {**bc.DEFAULTS, "max_steps": 6}


@pytest.fixture
def drv():
    return FakeDriver()


@pytest.fixture
def emitted():
    return []


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(bl, "sleep", lambda s: None)
    monkeypatch.setattr(bl, "image_part", lambda p: {"type": "image_url", "image_url": {"url": "data:x"}})


@pytest.fixture
def go(tmp_path, emitted):
    def _go(chat, drv, **kw):
        args = dict(chat=chat, model="m", effort="medium", cfg=CFG, shots_dir=tmp_path,
                    emit=lambda p, c: emitted.append((p, c)), stopped=lambda: False)
        return bl.run("任务", drv, **{**args, **kw})
    return _go


def tool_result(chat, i):
    return [m["content"] for m in chat.seen[-1] if m["role"] == "tool"][i]


def test_done_returns_report(go, drv):
    r = go(script([call("done", report="好了")]), drv)
    assert (r.status, r.report) == ("done", "好了")


def test_plain_content_is_report(go, drv):
    r = go(script("直接回答"), drv)
    assert r.status == "done" and r.report == "直接回答"


def test_meta_keys_not_sent_back(go, drv):
    chat = script([call("read_page")], [call("done", report="x")])
    go(chat, drv)
    assert all(not k.startswith("_") for m in chat.seen[-1] for k in m)


def test_read_page_is_fenced(go, drv):
    drv.snaps = [snap(el("e1", "button", "搜索"))]
    chat = script([call("read_page")], [call("done", report="x")])
    go(chat, drv)
    out = tool_result(chat, 0)
    assert rt.FENCE_NONCE in out and "e1 button 搜索" in out


def test_pay_click_refused_not_executed(go, drv):
    drv.snaps = [snap(el("e1", "button", "立即购买"))]
    chat = script([call("read_page")], [call("click", ref="e1")], [call("done", report="x")])
    r = go(chat, drv)
    assert ("click", "e1") not in drv.calls and r.blocked
    assert tool_result(chat, 1).startswith("[拦截]") and "已拦截的操作" in r.report


@pytest.mark.parametrize("url", ["file:///C:/a.txt", "http://127.0.0.1:9333/json", "http://192.168.1.1/"])
def test_local_navigation_refused(go, drv, url):
    r = go(script([call("navigate", url=url)], [call("done", report="x")]), drv)
    assert not drv.calls and r.blocked


def test_landing_on_cashier_goes_back(go, drv):
    drv.snaps = [snap(el("e1", "link", "下一步"))]
    drv.url_after_click = "https://cashier.alipay.com/x"
    r = go(script([call("read_page")], [call("click", ref="e1")], [call("done", report="x")]), drv)
    assert ("back",) in drv.calls and r.blocked


def test_about_blank_is_not_a_landing_refusal(go, drv):
    drv.current_url = "about:blank"
    r = go(script([call("press", key="Escape")], [call("done", report="x")]), drv)
    assert ("back",) not in drv.calls and not r.blocked


def test_password_type_refused(go, drv):
    drv.snaps = [snap(el("e1", "textbox", "密码", input_type="password"))]
    go(script([call("read_page")], [call("type", ref="e1", text="x")], [call("done", report="x")]), drv)
    assert not any(c[0] == "type" for c in drv.calls)


def test_type_allowed_field(go, drv):
    drv.snaps = [snap(el("e1", "textbox", "搜索"))]
    go(script([call("read_page")], [call("type", ref="e1", text="螳螂", submit=True)],
              [call("done", report="x")]), drv)
    assert ("type", "e1", "螳螂") in drv.calls


def test_stale_ref_recoverable(go, drv):
    chat = script([call("click", ref="e9")], [call("done", report="x")])
    r = go(chat, drv)
    assert tool_result(chat, 0).startswith("[错误]") and r.status == "done"


def test_driver_error_continues(go, drv):
    drv.fail_next = bd.DriverError("超时")
    chat = script([call("navigate", url="https://a.com")], [call("done", report="ok")])
    r = go(chat, drv)
    assert r.status == "done" and tool_result(chat, 0) == "[错误] 超时"


def test_browser_gone_ends_job(go, drv):
    drv.fail_next = bd.DriverGone("x")
    r = go(script([call("navigate", url="https://a.com")]), drv)
    assert r.status == "error" and "浏览器" in r.report


def test_unknown_tool_and_bad_json(go, drv):
    chat = script([call("fly")], [raw_call("click", "{not json")], [call("done", report="x")])
    r = go(chat, drv)
    assert tool_result(chat, 0).startswith("[错误] 未知工具")
    assert tool_result(chat, 1).startswith("[错误] 参数")
    assert r.status == "done"


def test_old_snapshots_collapse(go, drv):
    chat = script(*[[call("read_page")]] * 3, [call("done", report="x")])
    go(chat, drv)
    tools = [m["content"] for m in chat.seen[-1] if m["role"] == "tool"]
    assert sum(rt.FENCE_NONCE in t for t in tools) == 1 and tools[0].startswith("[旧页面")


def test_screenshot_sent_and_shown_after_tool_results(go, drv, emitted, tmp_path):
    chat = script([call("screenshot", send=True, caption="首页"), call("read_page")],
                  [call("done", report="x")])
    go(chat, drv)
    assert emitted[0][1] == "首页" and Path(emitted[0][0]).parent == tmp_path
    roles = [m["role"] for m in chat.seen[1]]
    assert roles[-3:] == ["tool", "tool", "user"]
    assert isinstance(chat.seen[1][-1]["content"], list)


def test_unsent_screenshot_only_for_model(go, drv, emitted):
    go(script([call("screenshot", send=False)], [call("done", report="x")]), drv)
    assert emitted == []


def test_no_image_message_without_vision(go, drv):
    chat = script([call("screenshot", send=True, caption="c")], [call("done", report="x")])
    go(chat, drv, sees_images=False)
    assert all(isinstance(m["content"], str) for m in chat.seen[1] if m["role"] == "user")


def test_only_two_newest_images_kept(go, drv):
    chat = script(*[[call("screenshot")]] * 3, [call("done", report="x")])
    go(chat, drv)
    assert sum(isinstance(m["content"], list) for m in chat.seen[-1]) == 2


def test_sent_screenshot_cap(go, drv, emitted):
    go(script(*[[call("screenshot", send=True, caption="c")]] * 3, [call("done", report="x")]),
       drv, cfg={**CFG, "max_sent_shots": 2})
    assert len(emitted) == 2


def test_save_image_collected(go, drv):
    drv.snaps = [snap(el("e1", "image", "猫"))]
    r = go(script([call("read_page")], [call("save_image", ref="e1")], [call("done", report="x")]), drv)
    assert len(r.images) == 1 and Path(r.images[0]).is_file()


def test_step_cap_wraps_up(go, drv):
    chat = script(*[[call("wait", seconds=0)]] * 6, "半成品报告")
    r = go(chat, drv)
    assert r.status == "steps" and r.report.startswith("半成品报告")
    assert chat.seen[-1][-1] == {"role": "user", "content": bl.WRAP_UP}


def test_wrap_up_tool_calls_ignored(go, drv):
    chat = script([call("navigate", url="https://a.com")])
    r = go(chat, drv, stopped=lambda: True)
    assert r.status == "stopped" and not drv.calls


def test_stop_flag(go, drv):
    r = go(script("停下的报告"), drv, stopped=lambda: True)
    assert r.status == "stopped" and r.report == "停下的报告"


def test_timeout(go, drv):
    t = itertools.chain([0], itertools.repeat(10_000))
    r = go(script("超时报告"), drv, clock=lambda: next(t))
    assert r.status == "timeout" and r.report == "超时报告"


def test_model_silent_twice_is_error(go, drv):
    r = go(lambda *a, **k: None, drv)
    assert r.status == "error"


def test_model_silent_once_retried(go, drv):
    replies = iter([None, {"role": "assistant", "content": "好"}])
    r = go(lambda *a, **k: next(replies), drv)
    assert (r.status, r.report) == ("done", "好")


def test_chat_called_without_fallback(go, drv):
    seen = {}

    def chat(messages, tools, model, effort, **kw):
        seen.update(kw)
        return {"role": "assistant", "content": "x"}
    go(chat, drv)
    assert seen.get("fallback") is False
