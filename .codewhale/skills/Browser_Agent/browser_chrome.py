"""可见 Chrome 进程：找、按成员 profile 启动、复用、关闭。设计：docs/superpowers/specs/2026-11-25-browser-agent-design.md「Chrome」。

Chrome 以普通进程启动（无自动化旗标），开本机调试端口，驱动经端口挂上。
同一时刻只有一个 Chrome（一个窗口、一个端口）；换成员先关旧的。
状态 data/.state/.browser_chrome.json：{member, pid, port, last_used}。
"""

from __future__ import annotations

import os
import subprocess
import time
import urllib.request
from pathlib import Path

import jsonfile
import paths as _paths

_LAUNCH_WAIT_S = 15
_CLOSE_WAIT_S = 5


class ChromeError(Exception):
    """起不来 / 找不到浏览器；消息直接给用户看。"""


def find_chrome(configured: str = "") -> str | None:
    """config 指定 → Chrome → Edge / PATH。浏览器位置表只在 PDF_Editor/pdf_create.py 一处。"""
    import pdf_create  # 延迟：导入本模块不拉起 PDF_Editor
    return pdf_create.find_browser(configured, prefer="chrome")


def launch_argv(exe: str, profile: Path, port: int) -> list[str]:
    return [exe, f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
            "--no-first-run", "--no-default-browser-check",
            "--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding",
            "about:blank"]


def endpoint(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def is_up(port: int) -> bool:
    try:
        with urllib.request.urlopen(endpoint(port) + "/json/version", timeout=1):
            return True
    except Exception:
        return False


def _state_path() -> Path:
    return _paths.state_file(".browser_chrome.json")


def _state() -> dict:
    return jsonfile.load_dict(_state_path())


def owner() -> str:
    return _state().get("member", "")


def touch() -> None:
    st = _state()
    if st:
        st["last_used"] = time.time()
        jsonfile.save(_state_path(), st)


def idle_expired(cfg: dict, now: float | None = None) -> bool:
    st = _state()
    if not st:
        return False
    now = time.time() if now is None else now
    return now - float(st.get("last_used") or 0) > float(cfg["idle_close_min"]) * 60


def _kill(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        os.kill(pid, 9)


def _quit(ep: str) -> None:
    import browser_playwright  # 延迟：本模块不依赖 playwright
    browser_playwright.quit(ep)


def close(cfg: dict, *, quit_fn=None, kill_fn=None, probe=is_up, sleep=time.sleep) -> None:
    """先礼（Browser.close）后兵（杀进程）；状态文件总会清掉。"""
    port = cfg["port"]
    pid = _state().get("pid")
    try:
        if probe(port):
            try:
                (quit_fn or _quit)(endpoint(port))
            except Exception:
                pass
            for _ in range(int(_CLOSE_WAIT_S / 0.5)):
                if not probe(port):
                    break
                sleep(0.5)
            else:
                if pid:
                    (kill_fn or _kill)(pid)
    finally:
        _state_path().unlink(missing_ok=True)


def ensure(member: str, cfg: dict, *, popen=subprocess.Popen, probe=is_up, sleep=time.sleep,
           closer=None) -> str:
    """保证 member 的 Chrome 在跑，返回调试端点。别人的（或来历不明的）先关。"""
    port = cfg["port"]
    if probe(port):
        st = _state()
        if st.get("member") == member and st.get("port") == port:
            touch()
            return endpoint(port)
        (closer or close)(cfg)
        if probe(port):
            raise ChromeError(f"本机端口 {port} 被别的程序占用，config.json browser.port 换一个")
    exe = find_chrome(cfg["exe"])
    if not exe:
        raise ChromeError("找不到 Chrome：安装 Chrome，或在 config.json browser.exe 填 chrome.exe 路径")
    profile = _paths.member_browser_profile_dir(member)
    proc = popen(launch_argv(exe, profile, port),
                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(int(_LAUNCH_WAIT_S / 0.5)):
        if probe(port):
            jsonfile.save(_state_path(), {"member": member, "pid": proc.pid, "port": port,
                                          "last_used": time.time()})
            return endpoint(port)
        sleep(0.5)
    raise ChromeError(f"Chrome 启动后 {_LAUNCH_WAIT_S} 秒没响应")
