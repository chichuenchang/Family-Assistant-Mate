# tests/test_browser_agent.py — Browser_Agent manifest、browser-login CLI
import json
import subprocess
import sys

import agent_core
import browser_jobs as bj
import tool_runtime as rt

M = agent_core.REGISTRY.modules["Browser_Agent"]
CLI = rt.SKILLS_DIR / "Browser_Agent" / "cli.py"


def test_tools_registered_and_locked():
    r = agent_core.REGISTRY
    names = {"browse", "browse_stop"}
    assert names <= set(r.tool_map) and names <= r.context_tools & r.member_locked
    assert bj.deliver in r.media_ticks and bj.last_report in r.context_fns


def test_login_command_not_agent_callable():
    assert "browser-login" not in rt.ALLOWED


def test_browse_needs_channel():
    assert M.tool_browse({"task": "x"}).startswith("[错误]")


def test_browse_needs_task():
    assert M.tool_browse({"task": " ", "__channel": "wechat", "__user": "u"}).startswith("[错误]")


def test_browse_needs_playwright(monkeypatch):
    monkeypatch.setattr(M.importlib.util, "find_spec", lambda n: None)
    out = M.tool_browse({"task": "x", "__channel": "wechat", "__user": "u"})
    assert out.startswith("[错误]") and "pip install playwright" in out


def test_browse_submits(monkeypatch):
    got = []

    def submit(*a, **k):
        got.append(a)
        return "id", "已开始"
    monkeypatch.setattr(bj, "submit", submit)
    monkeypatch.setattr(M.importlib.util, "find_spec", lambda n: object())
    out = M.tool_browse({"task": "查机票", "__channel": "wechat", "__user": "u", "member": "Jim"})
    assert out == "已开始" and got[0] == ("查机票", "wechat", "u", "Jim")


def test_browse_busy_is_not_an_error(monkeypatch):
    monkeypatch.setattr(bj, "submit", lambda *a, **k: (None, "浏览器正忙"))
    monkeypatch.setattr(M.importlib.util, "find_spec", lambda n: object())
    assert M.tool_browse({"task": "x", "__channel": "wechat", "__user": "u"}) == "浏览器正忙"


def test_browse_stop_routes(monkeypatch):
    monkeypatch.setattr(bj, "stop", lambda ch, u: f"{ch}/{u}")
    assert M.tool_browse_stop({"__channel": "wechat", "__user": "u"}) == "wechat/u"


def test_prompt_routes_to_browse():
    assert any(r.startswith("browse：") for r in agent_core.REGISTRY.prompt_rules)


def _cli(*args, data_root):
    env = {**__import__("os").environ, "DATA_ROOT": str(data_root)}
    return subprocess.run([sys.executable, str(CLI), *args], capture_output=True, text=True,
                          encoding="utf-8", env=env)


def test_cli_login_unknown_member(tmp_path):
    (tmp_path / "members.json").write_text(json.dumps({"Jim": {"dir": "Jim"}}), encoding="utf-8")
    r = _cli("browser-login", "--member", "Nobody", data_root=tmp_path)
    assert r.returncode == 1 and "Jim" in r.stdout + r.stderr


def test_cli_login_refused_while_job_running(tmp_path):
    (tmp_path / "members.json").write_text(json.dumps({"Jim": {"dir": "Jim"}}), encoding="utf-8")
    d = tmp_path / ".state" / ".browser_jobs"
    d.mkdir(parents=True)
    (d / "x.json").write_text(json.dumps({"id": "x", "status": "running", "member": "Jim"}),
                              encoding="utf-8")
    r = _cli("browser-login", "--member", "Jim", data_root=tmp_path)
    assert r.returncode == 1 and "浏览任务进行中" in r.stdout + r.stderr
