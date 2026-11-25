# tests/test_browser_chrome.py — 可见 Chrome 的启动/复用/关闭与成员 profile（不起真浏览器）
import time

import pytest

import backup_sync
import browser_cfg
import browser_chrome as bc
import paths


class World:
    """假机器：调试端口是否在应答。"""
    up = False
    launches = 0
    closes = 0


class Popen:
    def __init__(self, argv, **kw):
        World.launches += 1
        World.up = True
        self.pid = 4242


def closer(cfg):
    World.closes += 1
    World.up = False


def ens(member, popen=Popen):
    return bc.ensure(member, browser_cfg.DEFAULTS, popen=popen, probe=lambda p: World.up,
                     sleep=lambda s: None, closer=closer)


@pytest.fixture(autouse=True)
def fresh(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    World.up = False
    World.launches = World.closes = 0
    monkeypatch.setattr(bc, "find_chrome", lambda configured="": "C:/chrome.exe")


def test_profile_dir_and_backup_exclusion():
    d = paths.member_browser_profile_dir("Jim")
    assert d.name == "browser_profile" and d.is_dir()
    assert "browser_profile" in backup_sync._HARD_EXCLUDE_DIRS


def test_load_cfg_overlays_defaults():
    c = browser_cfg.load({"browser": {"port": 9444, "_comment": "x"}})
    assert c["port"] == 9444 and c["max_steps"] == 60 and "_comment" not in c


def test_load_cfg_missing_block_is_defaults():
    assert browser_cfg.load({}) == browser_cfg.DEFAULTS


def test_argv_visible_and_unflagged(tmp_path):
    a = bc.launch_argv("C:/chrome.exe", tmp_path / "p", 9333)
    assert "--remote-debugging-port=9333" in a and f"--user-data-dir={tmp_path / 'p'}" in a
    assert not any("headless" in x or "enable-automation" in x for x in a)


def test_ensure_launches_when_down():
    assert ens("Jim") == "http://127.0.0.1:9333"
    assert World.launches == 1 and bc.owner() == "Jim"


def test_ensure_reuses_running_chrome_of_same_member():
    ens("Jim")
    ens("Jim")
    assert (World.launches, World.closes) == (1, 0)


def test_ensure_other_member_closes_first():
    ens("Jim")
    ens("Mom")
    assert (World.launches, World.closes) == (2, 1) and bc.owner() == "Mom"


def test_ensure_unowned_running_chrome_is_closed_not_adopted():
    World.up = True      # 端口在应答，状态文件为空（上次 bot 留下的，或别的程序）
    ens("Jim")
    assert (World.launches, World.closes) == (1, 1)


def test_ensure_no_browser_names_config_key(monkeypatch):
    monkeypatch.setattr(bc, "find_chrome", lambda configured="": None)
    with pytest.raises(bc.ChromeError, match="browser.exe"):
        ens("Jim")


def test_ensure_never_up_raises():
    class Dead:
        def __init__(self, argv, **kw):
            self.pid = 1
    with pytest.raises(bc.ChromeError):
        ens("Jim", popen=Dead)


def test_close_graceful_then_kill_fallback():
    ens("Jim")
    killed = []
    bc.close(browser_cfg.DEFAULTS, quit_fn=lambda ep: None, kill_fn=killed.append,
             probe=lambda p: True, sleep=lambda s: None)
    assert killed == [4242] and bc.owner() == ""


def test_close_graceful_no_kill():
    ens("Jim")
    killed = []

    def quit_fn(ep):
        World.up = False
    bc.close(browser_cfg.DEFAULTS, quit_fn=quit_fn, kill_fn=killed.append,
             probe=lambda p: World.up, sleep=lambda s: None)
    assert killed == [] and bc.owner() == ""


def test_idle_expired():
    ens("Jim")
    bc.touch()
    assert not bc.idle_expired(browser_cfg.DEFAULTS)
    assert bc.idle_expired(browser_cfg.DEFAULTS, now=time.time() + 31 * 60)


def test_idle_expired_false_without_chrome():
    assert not bc.idle_expired(browser_cfg.DEFAULTS, now=time.time() + 99 * 60)
