"""浏览任务：后台线程跑 browser_loop，截图途中推送，报告由 MEDIA_TICKS 投递（同 knowking_jobs 套路）。
设计：docs/superpowers/specs/2026-11-25-browser-agent-design.md「Shape」「Delivery」。

- 全机一个槽位（一个可见窗口）：任何人有 running 任务，新 browse 都回"正忙"。
- 任务文件 data/.state/.browser_jobs/<id>.json；任务线程追加 outbox，节拍线程推进 sent —— 读改写全在 _LOCK 内。
- 投递后保留 24 h：last_report 把最近报告（围栏）注入主 Agent，供"第二个""加购物车"之类跟进。
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Callable, Optional

import browser_cfg
import browser_chrome as bc
import jsonfile
import paths as _paths
import tool_runtime as rt
from browser_loop import Result

_log = logging.getLogger("fam.browser")
_LOCK = threading.Lock()
_STALE_GRACE_S = 300
_KEEP_DELIVERED_S = 24 * 3600
_CACHE_DAYS = 7


def jobs_dir(jdir: Optional[Path] = None) -> Path:
    d = Path(jdir) if jdir is not None else _paths.state_file(".browser_jobs")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(d: Path, jid: str) -> Path:
    return d / f"{jid}.json"


def _read(d: Path, jid: str) -> Optional[dict]:
    return jsonfile.load_dict(_path(d, jid)) or None


def _write(d: Path, job: dict) -> None:
    jsonfile.save(_path(d, job["id"]), job)


def _jobs(d: Path) -> list[dict]:
    return [j for f in sorted(d.glob("*.json")) if (j := jsonfile.load_dict(f))]


def _update(d: Path, jid: str, change: Callable[[dict], None]) -> Optional[dict]:
    with _LOCK:
        job = _read(d, jid)
        if job is None:
            return None
        change(job)
        _write(d, job)
        return job


# ── 提交 / 停止 ─────────────────────────────────────────

def _reap_orphans(d: Path, channel: str) -> None:
    """调用方持 _LOCK。本频道 running 任务的 pid 不是本进程 = 重启前遗留，线程已随旧进程死：
    不清就占着槽位到超时（~20 分钟）。只认本频道：别的频道可能是另一个活着的机器人进程。"""
    me = os.getpid()
    for j in _jobs(d):
        if j.get("status") == "running" and j.get("channel") == channel and j.get("pid") != me:
            j.update(status="error", error="机器人重启，浏览任务中断（可重试）")
            _write(d, j)


def busy(*, jdir: Optional[Path] = None) -> Optional[dict]:
    """占着浏览器槽位的任务（任何频道、任何人），没有 = None。"""
    return next((j for j in _jobs(jobs_dir(jdir)) if j.get("status") == "running"), None)


def submit(task: str, channel: str, user: str, member: str, *, background: bool = True,
           runner=None, jdir: Optional[Path] = None) -> tuple[Optional[str], str]:
    task = (task or "").strip()
    if not task:
        return None, "要我用浏览器做什么？请说清楚要查的内容。"
    d = jobs_dir(jdir)
    with _LOCK:
        _reap_orphans(d, channel)
        running = busy(jdir=d)
        if running:
            return None, (f"浏览器正忙（{running.get('member') or '别人'} 的任务进行中），"
                          "等它结束或让发起人说“停止浏览”。")
        jid = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        _write(d, {"id": jid, "pid": os.getpid(), "channel": channel, "user": str(user), "member": member or "",
                   "task": task, "status": "running", "report": "", "error": "",
                   "created_at": time.time(), "delivered_at": 0, "stop": False,
                   "outbox": [], "sent": 0, "images": [], "images_sent": False})
    if background:
        threading.Thread(target=_run_job, args=(jid,), kwargs={"runner": runner, "jdir": d},
                         daemon=True, name=f"browse-{jid}").start()
    return jid, "🌐 已打开浏览器开始处理，过程中的截图和最终结果会自动发你。"


def stop(channel: str, user: str, *, jdir: Optional[Path] = None) -> str:
    d = jobs_dir(jdir)
    with _LOCK:
        for job in _jobs(d):
            if (job.get("status") == "running" and job.get("channel") == channel
                    and job.get("user") == str(user)):
                job["stop"] = True
                _write(d, job)
                return "已通知停止，稍后发你已查到的部分。"
    return "你没有进行中的浏览任务。"


# ── 运行 ────────────────────────────────────────────────

def _emit(d: Path, jid: str, path: str, caption: str) -> None:
    _update(d, jid, lambda j: j["outbox"].append({"path": _paths.to_rel(path), "caption": caption}))


def _default_runner(job: dict, emit, stopped) -> Result:
    import browser_loop
    import llm_client
    cfg = browser_cfg.load()
    member = job["member"]
    shots = _paths.member_cache_dir(member, "browser")
    _paths.prune_older(shots, _CACHE_DAYS)
    try:
        ep = bc.ensure(member, cfg)
    except bc.ChromeError as e:
        return Result("error", str(e))
    import browser_playwright   # 延迟：缺 playwright 时只坏这里
    driver = browser_playwright.PlaywrightDriver(ep, humanize=bool(cfg["humanize"]),
                                                 speed=float(cfg["speed"]))
    model = (llm_client.canon_model(cfg["model"])
             or llm_client.settings(llm_client.load_overrides(), "")[0])
    try:
        return browser_loop.run(job["task"], driver, chat=llm_client.chat, model=model,
                                effort=cfg["effort"], cfg=cfg, shots_dir=shots, emit=emit,
                                stopped=stopped, sees_images=llm_client.sees_images(model))
    finally:
        driver.close()
        bc.touch()


def _run_job(jid: str, *, runner=None, jdir: Optional[Path] = None) -> None:
    d = jobs_dir(jdir)
    job = _read(d, jid)
    if job is None:
        return
    try:
        res = (runner or _default_runner)(
            job, lambda p, c: _emit(d, jid, p, c),
            lambda: bool((_read(d, jid) or {}).get("stop")))
    except Exception as e:  # noqa: BLE001 — 任何失败都落成 error，绝不外抛
        _log.exception("浏览任务异常: %s", jid)
        res = Result("error", f"内部错误：{e}")

    def finish(j: dict) -> None:
        if j.get("status") != "running":     # 已被判超时，不覆盖
            return
        if res.status == "error":
            j["status"], j["error"] = "error", res.report
        else:
            j["status"], j["report"] = "done", res.report
        j["images"] = [_paths.to_rel(p) for p in res.images]
    _update(d, jid, finish)


# ── 投递（MEDIA_TICKS） ─────────────────────────────────

def _push_outbox(d: Path, job: dict, push_photo) -> None:
    for i in range(int(job.get("sent") or 0), len(job.get("outbox") or [])):
        try:
            push_photo(job["user"], job["outbox"][i]["path"])
        except Exception:  # noqa: BLE001
            _log.exception("截图推送失败（跳过）")
        _update(d, job["id"], lambda j, n=i + 1: j.update(sent=n))


def _text(job: dict) -> str:
    if job["status"] == "done":
        return f"🌐 浏览结果 —「{job['task'][:40]}」\n\n{job['report']}"
    return f"⚠️ 浏览任务失败：{job.get('error') or '未知原因'}"


def _close_chrome(close: Callable[[dict], None], cfg: dict, why: str) -> None:
    try:
        close(cfg)
    except Exception:  # noqa: BLE001
        _log.exception("%s关 Chrome 失败", why)


def deliver(push_text, push_photo, channel: str, *, jdir: Optional[Path] = None,
            now: float | None = None, close_chrome: Optional[Callable[[dict], None]] = None) -> int:
    """close_chrome 缺省：真实任务目录用 bc.close；测试目录（jdir）不碰真 Chrome。"""
    close = close_chrome or (bc.close if jdir is None else (lambda cfg: None))
    d = jobs_dir(jdir)
    now = time.time() if now is None else now
    cfg = browser_cfg.load()
    with _LOCK:
        _reap_orphans(d, channel)
    count = 0
    for job in _jobs(d):
        if job.get("channel") != channel:
            continue
        jid, status = job["id"], job.get("status")
        if status == "delivered":
            if now - float(job.get("delivered_at") or 0) > _KEEP_DELIVERED_S:
                _path(d, jid).unlink(missing_ok=True)
            continue
        if status == "running":
            if now - float(job.get("created_at") or 0) <= float(cfg["timeout_s"]) + _STALE_GRACE_S:
                _push_outbox(d, job, push_photo)
                continue
            stalled = []

            def mark(j: dict) -> None:
                if j.get("status") == "running":          # 线程恰好刚收尾就不算卡死
                    j.update(status="error", error="浏览任务超时或中断（可重试）")
                    stalled.append(j["id"])
            job = _update(d, jid, mark) or job
            if stalled:
                # 线程卡死（evaluate 等调用不受 Playwright 超时管）：关 Chrome，卡住的调用随连接断开
                # 报错退出，下一个任务不会和它共用浏览器。进程内唯一的强制终止手段（ADR 0001）。
                _close_chrome(close, cfg, "超时任务")
        if job.get("status") not in ("done", "error"):
            continue
        _push_outbox(d, job, push_photo)
        if not job.get("images_sent"):
            for rel in job.get("images") or []:
                try:
                    push_photo(job["user"], rel)
                except Exception:  # noqa: BLE001
                    _log.exception("图片推送失败（跳过）")
            _update(d, jid, lambda j: j.update(images_sent=True))
        try:
            ok = push_text(job["user"], _text(job)) is not False
        except Exception:  # noqa: BLE001 — 下拍重试
            _log.exception("浏览报告投递失败，下拍重试: %s", jid)
            ok = False
        if not ok:
            continue
        _update(d, jid, lambda j: j.update(status="delivered", delivered_at=now,
                                          outcome=j.get("status")))
        count += 1
    if jdir is None and busy(jdir=d) is None and bc.idle_expired(cfg):
        _close_chrome(close, cfg, "空闲")
    return count


def last_report(member: str, *, jdir: Optional[Path] = None, now: float | None = None) -> str:
    """CONTEXT_FNS：最近一次已投递的成功浏览报告（idle_clear_hours 内），围栏后注入。"""
    now = time.time() if now is None else now
    hours = float((rt.CONFIG.get("agent") or {}).get("idle_clear_hours", 4) or 0)   # 同 agent_core：0 = 不清
    ttl = hours * 3600 if hours > 0 else _KEEP_DELIVERED_S
    best = None
    for j in _jobs(jobs_dir(jdir)):
        if (j.get("member") == member and j.get("status") == "delivered"
                and j.get("outcome") == "done" and now - float(j.get("delivered_at") or 0) <= ttl
                and (best is None or j["delivered_at"] > best["delivered_at"])):
            best = j
    if best is None:
        return ""
    return f"\n\n## 最近一次浏览任务\n任务：{best['task']}\n" + rt.fence(best["report"], "browser")
