# tests/test_browser_jobs.py — 浏览任务：全机一个槽位、停止、截图途中推送、报告投递、跟进上下文
import json
import threading
import time

import pytest

import browser_jobs as bj
import tool_runtime as rt
from browser_loop import Result


@pytest.fixture
def jdir(tmp_path):
    d = tmp_path / "jobs"
    d.mkdir()
    return d


@pytest.fixture
def pushes():
    return []


@pytest.fixture
def pt(pushes):
    def push_text(user, text):
        pushes.append(("text", user, text))
        return True
    return push_text


@pytest.fixture
def pp(pushes):
    def push_photo(user, rel):
        pushes.append(("photo", user, rel))
        return True
    return push_photo


def ok(job, emit, stopped):
    return Result("done", "报告", [], [])


def boom(job, emit, stopped):
    raise RuntimeError("炸了")


def job(jdir, jid):
    p = jdir / f"{jid}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def sub(jdir, task="查机票", channel="wechat", user="u1", member="Jim"):
    jid, _ = bj.submit(task, channel, user, member, background=False, jdir=jdir)
    assert jid
    return jid


def queue(jdir, jid, path, caption):
    """模拟任务线程途中 emit 一张截图。"""
    bj._emit(jdir, jid, path, caption)


def finished(jdir, outbox=(), images=()):
    jid = sub(jdir)

    def runner(job, emit, stopped):
        for p in outbox:
            emit(p, "途中")
        return Result("done", "报告", list(images), [])
    bj._run_job(jid, runner=runner, jdir=jdir)
    return jid


def test_submit_writes_running_and_acks(jdir):
    jid, ack = bj.submit("查机票", "wechat", "u1", "Jim", background=False, jdir=jdir)
    assert jid and "浏览器" in ack and job(jdir, jid)["status"] == "running"


def test_empty_task_rejected(jdir):
    assert bj.submit("  ", "wechat", "u1", "Jim", jdir=jdir)[0] is None


def test_busy_is_global_across_users(jdir):
    sub(jdir)
    jid, msg = bj.submit("b", "telegram", "u2", "Mom", background=False, jdir=jdir)
    assert jid is None and "Jim" in msg


def test_busy_reports_running_job_until_finished(jdir):
    jid = sub(jdir)
    assert bj.busy(jdir=jdir)["id"] == jid
    bj._run_job(jid, runner=ok, jdir=jdir)
    assert bj.busy(jdir=jdir) is None


def test_run_success(jdir):
    jid = sub(jdir)
    bj._run_job(jid, runner=ok, jdir=jdir)
    assert job(jdir, jid)["status"] == "done" and job(jdir, jid)["report"] == "报告"


def test_run_error_result(jdir):
    jid = sub(jdir)
    bj._run_job(jid, runner=lambda *a: Result("error", "窗口关了", [], []), jdir=jdir)
    assert job(jdir, jid)["status"] == "error" and job(jdir, jid)["error"] == "窗口关了"


def test_runner_raising_becomes_error(jdir):
    jid = sub(jdir)
    bj._run_job(jid, runner=boom, jdir=jdir)
    assert job(jdir, jid)["status"] == "error" and "炸了" in job(jdir, jid)["error"]


def test_slot_freed_after_finish(jdir):
    jid = sub(jdir)
    bj._run_job(jid, runner=ok, jdir=jdir)
    assert bj.submit("b", "wechat", "u1", "Jim", background=False, jdir=jdir)[0]


def test_stop_sets_flag_runner_sees_it(jdir):
    jid = sub(jdir)
    assert "停止" in bj.stop("wechat", "u1", jdir=jdir)
    seen = []

    def runner(job, emit, stopped):
        seen.append(stopped())
        return Result("stopped", "部分", [], [])
    bj._run_job(jid, runner=runner, jdir=jdir)
    assert seen == [True] and job(jdir, jid)["status"] == "done"


def test_stop_other_user_not_affected(jdir):
    sub(jdir)
    assert "没有" in bj.stop("wechat", "u2", jdir=jdir)


def test_stop_without_job(jdir):
    assert "没有" in bj.stop("wechat", "u1", jdir=jdir)


def test_photos_pushed_mid_run_once_in_order(jdir, pt, pp, pushes):
    jid = sub(jdir)
    queue(jdir, jid, "a.png", "一")
    queue(jdir, jid, "b.png", "二")
    bj.deliver(pt, pp, "wechat", jdir=jdir)
    bj.deliver(pt, pp, "wechat", jdir=jdir)
    assert [p for kind, _, p in pushes if kind == "photo"] == ["a.png", "b.png"]
    assert not [k for k, *_ in pushes if k == "text"]


def test_done_delivers_photos_images_then_text(jdir, pt, pp, pushes):
    jid = finished(jdir, outbox=["s.png"], images=["i.jpg"])
    assert bj.deliver(pt, pp, "wechat", jdir=jdir) == 1
    assert [k for k, *_ in pushes] == ["photo", "photo", "text"]
    assert pushes[-1][1] == "u1" and "报告" in pushes[-1][2] and "查机票" in pushes[-1][2]
    assert job(jdir, jid)["status"] == "delivered"


def test_error_job_delivers_warning(jdir, pt, pp, pushes):
    jid = sub(jdir)
    bj._run_job(jid, runner=boom, jdir=jdir)
    bj.deliver(pt, pp, "wechat", jdir=jdir)
    assert pushes[-1][2].startswith("⚠️")


def test_channel_filter(jdir, pt, pp):
    finished(jdir)
    assert bj.deliver(pt, pp, "telegram", jdir=jdir) == 0


def test_text_failure_retries_without_resending_photos(jdir, pt, pp, pushes):
    finished(jdir, outbox=["s.png"])
    bj.deliver(lambda u, t: False, pp, "wechat", jdir=jdir)
    bj.deliver(pt, pp, "wechat", jdir=jdir)
    assert [k for k, *_ in pushes] == ["photo", "text"]


def test_text_push_raising_is_retried(jdir, pt, pp, pushes):
    finished(jdir)

    def bad(u, t):
        raise OSError("网断了")
    assert bj.deliver(bad, pp, "wechat", jdir=jdir) == 0
    assert bj.deliver(pt, pp, "wechat", jdir=jdir) == 1


def test_photo_failure_skipped(jdir, pt):
    finished(jdir, outbox=["s.png"])
    assert bj.deliver(pt, lambda u, p: False, "wechat", jdir=jdir) == 1


def test_stale_running_becomes_error_and_frees_slot(jdir, pt, pp, pushes):
    sub(jdir)
    bj.deliver(pt, pp, "wechat", jdir=jdir, now=time.time() + 900 + 301)
    assert "中断" in pushes[-1][2]
    assert bj.submit("b", "wechat", "u1", "Jim", background=False, jdir=jdir)[0]


def orphan(jdir, channel="wechat"):
    """模拟重启前留下的 running 任务（pid 属于已死的旧进程）。"""
    jid = sub(jdir, channel=channel)
    p = jdir / f"{jid}.json"
    j = json.loads(p.read_text(encoding="utf-8"))
    j["pid"] = -1
    p.write_text(json.dumps(j, ensure_ascii=False), encoding="utf-8")
    return jid


def test_orphan_after_restart_frees_slot_now(jdir):
    old = orphan(jdir)
    assert bj.submit("b", "wechat", "u1", "Jim", background=False, jdir=jdir)[0]
    assert job(jdir, old)["status"] == "error"


def test_orphan_reported_on_next_tick(jdir, pt, pp, pushes):
    orphan(jdir)
    assert bj.deliver(pt, pp, "wechat", jdir=jdir) == 1
    assert "重启" in pushes[-1][2]


def test_other_channels_running_job_not_reaped(jdir):
    other = orphan(jdir, channel="telegram")
    assert bj.submit("b", "wechat", "u1", "Jim", background=False, jdir=jdir)[0] is None
    assert job(jdir, other)["status"] == "running"


def test_last_report_fenced_within_ttl(jdir, pt, pp):
    finished(jdir)
    bj.deliver(pt, pp, "wechat", jdir=jdir)
    out = bj.last_report("Jim", jdir=jdir)
    assert "报告" in out and rt.FENCE_NONCE in out and "查机票" in out


def test_last_report_only_after_delivery(jdir):
    finished(jdir)
    assert bj.last_report("Jim", jdir=jdir) == ""


def test_last_report_other_member_or_expired(jdir, pt, pp):
    finished(jdir)
    bj.deliver(pt, pp, "wechat", jdir=jdir)
    assert bj.last_report("Mom", jdir=jdir) == ""
    assert bj.last_report("Jim", jdir=jdir, now=time.time() + 5 * 3600) == ""


def test_delivered_pruned_after_a_day(jdir, pt, pp):
    jid = finished(jdir)
    bj.deliver(pt, pp, "wechat", jdir=jdir)
    bj.deliver(pt, pp, "wechat", jdir=jdir, now=time.time() + 25 * 3600)
    assert job(jdir, jid) is None


def test_concurrent_submits_one_wins(jdir):
    results = []
    barrier = threading.Barrier(8)

    def worker(i):
        barrier.wait()
        results.append(bj.submit(f"t{i}", "wechat", f"u{i}", "Jim", background=False, jdir=jdir)[0])
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(r is not None for r in results) == 1
