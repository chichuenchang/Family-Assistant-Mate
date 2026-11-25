"""transport_base：频道共用生命周期（闸门 / 投递 / 异常兜底 / 后台节拍）。"""
import agent_core
import tool_runtime as rt
import transport_base as tb


class FakeTransport(tb.Transport):
    channel = "telegram"
    tag = "fk"

    def __init__(self, agent=None):
        super().__init__(agent)
        self.calls = []

    def send_text(self, target, text):
        self.calls.append(("text", target, text))

    def send_photo(self, target, path):
        self.calls.append(("photo", target, path))

    def send_document(self, target, path):
        self.calls.append(("doc", target, path))

    def after_text_sent(self, target, text):
        self.calls.append(("after", target, text))


class FakeAgent:
    def __init__(self, reply="ok", boom=False):
        self.reply, self.boom, self.seen = reply, boom, []

    def handle(self, text, user="", member="", said=None):
        self.said = said
        self.seen.append(("text", text, user, member))
        if self.boom:
            raise RuntimeError("llm down")
        return agent_core.Reply(self.reply)

    def handle_media(self, paths, text, user="", member="", said=None):
        self.said = said
        self.seen.append(("media", paths, text, user, member))
        if self.boom:
            raise RuntimeError("ocr down")
        return agent_core.Reply(self.reply)


def _seed(tmp_path):
    img = tmp_path / "Alex" / "charts" / "c.png"
    img.parent.mkdir(parents=True)
    img.write_bytes(b"\x89PNG")
    doc = tmp_path / "Family" / "documents" / "d.pdf"
    doc.parent.mkdir(parents=True)
    doc.write_bytes(b"%PDF")
    return "Alex/charts/c.png", "Family/documents/d.pdf"


def test_with_quote():
    assert tb.with_quote("hi", "prev") == f"[引用]\n{rt.fence('prev', 'quote')}\nhi"
    assert tb.with_quote("hi", None) == "hi"


def test_deliver_photo_then_doc_then_text_then_hook(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    img, doc = _seed(tmp_path)
    t = FakeTransport(agent=FakeAgent())
    t.deliver(7, agent_core.Reply("说明", [img], [doc]))
    assert [c[0] for c in t.calls] == ["photo", "doc", "text", "after"]
    assert t.calls[2] == ("text", 7, "说明")


def test_deliver_gates_missing_and_escaping_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    t = FakeTransport(agent=FakeAgent())
    t.deliver(7, agent_core.Reply("hi", ["Alex/missing.png"], ["../../etc/passwd"]))
    assert t.calls == [("text", 7, "hi"), ("after", 7, "hi")]


def test_deliver_empty_reply_sends_nothing():
    t = FakeTransport(agent=FakeAgent())
    t.deliver(7, agent_core.Reply())
    assert t.calls == []


def test_one_failed_attachment_does_not_block_text(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    img, _ = _seed(tmp_path)
    t = FakeTransport(agent=FakeAgent())
    t.send_photo = lambda target, path: (_ for _ in ()).throw(RuntimeError("net"))
    t.deliver(7, agent_core.Reply("文字", [img]))
    assert ("text", 7, "文字") in t.calls


def test_on_text_ticks_quotes_and_delivers(monkeypatch):
    ticks = []
    monkeypatch.setattr(tb.REGISTRY, "message_ticks",
                        [lambda: ticks.append("cal"), lambda: ticks.append("gc")])
    agent = FakeAgent(reply="回")
    t = FakeTransport(agent=agent)
    t.on_text("tgt", 42, "Alex", "你好", quoted="上一条")
    assert ticks == ["cal", "gc"]
    assert agent.seen == [("text", tb.with_quote("你好", "上一条"), "42", "Alex")]
    assert agent.said == "你好"          # 确认闸门只认用户亲手打的字，不含引用
    assert ("text", "tgt", "回") in t.calls


def test_on_text_agent_exception_reports_not_crashes(monkeypatch):
    monkeypatch.setattr(tb.REGISTRY, "message_ticks", [])
    t = FakeTransport(agent=FakeAgent(boom=True))
    t.on_text("tgt", 1, "Alex", "x")
    assert t.calls and t.calls[0][2].startswith("处理出错")


def test_on_media_none_path_asks_resend(monkeypatch):
    monkeypatch.setattr(tb.REGISTRY, "message_ticks", [])
    agent = FakeAgent()
    t = FakeTransport(agent=agent)
    t.on_media("tgt", 1, "Alex", None)
    assert agent.seen == []
    assert "重发" in t.calls[0][2]


def test_on_media_silent_until_text_then_batched(monkeypatch, tmp_path):
    monkeypatch.setattr(tb.REGISTRY, "message_ticks", [])
    agent = FakeAgent(reply="收到")
    t = FakeTransport(agent=agent)
    t.on_media("tgt", 1, "Alex", tmp_path / "a.jpg")
    t.on_media("tgt", 1, "Alex", tmp_path / "b.pdf")
    t.on_media("tgt", 2, "Bo", tmp_path / "c.jpg")     # 别的用户的来件不串
    assert agent.seen == [] and t.calls == []
    t.on_text("tgt", 1, "Alex", "记账", quoted="上一条")
    assert agent.seen == [("media", [str(tmp_path / "a.jpg"), str(tmp_path / "b.pdf")],
                           tb.with_quote("记账", "上一条"), "1", "Alex")]
    assert agent.said == "记账"
    assert ("text", "tgt", "收到") in t.calls
    t.on_text("tgt", 1, "Alex", "再问")                # 来件已用掉 → 普通对话
    assert agent.seen[-1] == ("text", "再问", "1", "Alex")


def test_failed_media_turn_keeps_media(monkeypatch, tmp_path):
    monkeypatch.setattr(tb.REGISTRY, "message_ticks", [])
    agent = FakeAgent(boom=True)
    t = FakeTransport(agent=agent)
    t.on_media("tgt", 1, "Alex", tmp_path / "a.jpg")
    t.on_text("tgt", 1, "Alex", "记账")
    assert t.calls[0][2].startswith("处理出错")
    agent.boom = False
    t.on_text("tgt", 1, "Alex", "记账")                 # 重发指令，来件还在
    assert agent.seen[-1][:2] == ("media", [str(tmp_path / "a.jpg")])


def test_stale_media_expires_with_idle_clear(monkeypatch, tmp_path):
    monkeypatch.setattr(tb.REGISTRY, "message_ticks", [])
    agent = FakeAgent()
    agent.idle_clear_seconds = 3600
    t = FakeTransport(agent=agent)
    now = [1000.0]
    monkeypatch.setattr(tb.time, "time", lambda: now[0])
    t.on_media("tgt", 1, "Alex", tmp_path / "old.jpg")
    now[0] += 3600
    t.on_media("tgt", 1, "Alex", tmp_path / "new.jpg")
    t.on_text("tgt", 1, "Alex", "记账")
    assert agent.seen[-1][:2] == ("media", [str(tmp_path / "new.jpg")])
    t.on_media("tgt", 1, "Alex", tmp_path / "x.jpg")
    now[0] += 3600
    t.on_text("tgt", 1, "Alex", "记一笔 午餐45块")     # 只剩过期来件 → 普通对话
    assert agent.seen[-1] == ("text", "记一笔 午餐45块", "1", "Alex")


def test_explicit_media_leaves_held_alone(monkeypatch, tmp_path):
    monkeypatch.setattr(tb.REGISTRY, "message_ticks", [])
    agent = FakeAgent()
    t = FakeTransport(agent=agent)
    t.on_media("tgt", 1, "Alex", tmp_path / "old.jpg")
    t.on_text("tgt", 1, "Alex", "记账", media=[tmp_path / "r.jpg"])
    assert agent.seen[-1][:2] == ("media", [str(tmp_path / "r.jpg")])
    t.on_text("tgt", 1, "Alex", "/model", media=[tmp_path / "c.jpg"])   # 命令附言：来件照攒
    t.on_text("tgt", 1, "Alex", "这两张")
    assert agent.seen[-1][:2] == ("media", [str(tmp_path / "old.jpg"), str(tmp_path / "c.jpg")])


def test_commands_bypass_pending_media(monkeypatch, tmp_path):
    monkeypatch.setattr(tb.REGISTRY, "message_ticks", [])
    agent = FakeAgent()
    t = FakeTransport(agent=agent)
    t.on_media("tgt", 1, "Alex", tmp_path / "a.jpg")
    t.on_text("tgt", 1, "Alex", "/model")               # 命令照常执行，来件继续等
    assert agent.seen == [("text", "/model", "1", "Alex")]
    t.on_text("tgt", 1, "Alex", "/clear")               # /clear 连来件一起清
    assert agent.seen[-1] == ("text", "/clear", "1", "Alex")
    t.on_text("tgt", 1, "Alex", "你好")
    assert agent.seen[-1] == ("text", "你好", "1", "Alex")


def test_gate_uses_channel_registry(monkeypatch):
    seen = {}

    def fake_resolve(channel, cid):
        seen.update(channel=channel, cid=cid)
        return "Alex" if cid == "1" else None

    monkeypatch.setattr(tb, "resolve", fake_resolve)
    t = FakeTransport(agent=FakeAgent())
    assert t.gate(1) == "Alex" and seen == {"channel": "telegram", "cid": "1"}
    assert t.gate(2) is None


def test_inbox_path_uses_member_inbox_and_channel(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    t = FakeTransport(agent=FakeAgent())
    p = t.inbox_path("Alex", ".pdf")
    assert p.name.endswith("_telegram.pdf")
    assert p.parent.is_relative_to(tmp_path)
    assert t.inbox_path("Alex", ".pdf") != p          # 同秒连发不互相覆盖


def test_background_tick_isolates_failures(monkeypatch):
    order = []
    monkeypatch.setattr(tb.REGISTRY, "slow_ticks", [
        lambda send, ch: (_ for _ in ()).throw(RuntimeError("r")),
        lambda send, ch: order.append(("backup", ch))])
    monkeypatch.setattr(tb.REGISTRY, "fast_ticks", [lambda send, ch: order.append(("kk", ch))])
    t = FakeTransport(agent=FakeAgent())
    t.background_tick()
    assert order == [("backup", "telegram"), ("kk", "telegram")]


def test_real_manifests_register_ticks():
    names = lambda fns: {getattr(f, "__name__", "") for f in fns}
    assert "image_gc_tick" in names(tb.REGISTRY.message_ticks)
    assert "calendar_tick" not in names(tb.REGISTRY.message_ticks)
    assert {"check_and_push", "backup_tick"} <= names(tb.REGISTRY.slow_ticks)
    assert "poll_and_deliver" in names(tb.REGISTRY.fast_ticks)


def test_agent_is_lazy():
    t = FakeTransport()
    assert t._agent is None
    t.deliver(1, agent_core.Reply("只发文字"))           # 投递不构造 Agent
    assert t._agent is None


def test_push_text_records_sent_for_quote_lookup():
    t = FakeTransport()
    assert t.push_text("u1", "新邮件") is True
    assert t.calls == [("text", "u1", "新邮件"), ("after", "u1", "新邮件")]


def test_failed_push_text_not_recorded():
    class Refusing(FakeTransport):
        def send_text(self, target, text):
            return False
    t = Refusing()
    assert t.push_text("u1", "新邮件") is False
    assert t.calls == []


# ── 后台推图（MEDIA_TICKS：浏览截图途中推送） ────────────────

def test_push_photo_gated_and_sent(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    img, _ = _seed(tmp_path)
    t = FakeTransport()
    assert t.push_photo("u1", img) is True
    assert t.calls[-1][:2] == ("photo", "u1")


def test_push_photo_refuses_outside_data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path / "d"))
    (tmp_path / "secret.png").write_bytes(b"x")
    t = FakeTransport()
    assert t.push_photo("u1", "../secret.png") is False and t.calls == []


def test_push_photo_false_when_send_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    img, _ = _seed(tmp_path)
    t = FakeTransport()
    t.send_photo = lambda target, path: (_ for _ in ()).throw(RuntimeError("net"))
    assert t.push_photo("u1", img) is False


def test_push_photo_false_when_send_returns_false(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    img, _ = _seed(tmp_path)
    t = FakeTransport()
    t.send_photo = lambda target, path: False
    assert t.push_photo("u1", img) is False


def test_fast_tick_runs_media_ticks_with_three_args(monkeypatch):
    got = []
    monkeypatch.setattr(tb.REGISTRY, "fast_ticks", [])
    monkeypatch.setattr(tb.REGISTRY, "media_ticks",
                        [lambda pt, pp, ch: got.append((pt.__name__, pp.__name__, ch))])
    t = FakeTransport()
    t.fast_tick()
    assert got == [("push_text", "push_photo", t.channel)]
