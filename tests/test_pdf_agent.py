# tests/test_pdf_agent.py — PDF_Editor 的 agent_core 接线（取代 Form_Filler）。
import agent_core

PDF_TOOLS = {"inspect_pdf", "edit_pdf", "pdf_edit_list", "pdf_pages"}


def test_commands_allowed_and_routed():
    for c in ("pdf-inspect", "pdf-edit", "pdf-list", "pdf-pages"):
        assert c in agent_core.rt.ALLOWED
        assert agent_core.rt.cli_path(c).parent.name == "PDF_Editor"


def test_tools_registered_with_schema():
    names = {t["function"]["name"] for t in agent_core.REGISTRY.schemas}
    assert PDF_TOOLS <= names
    assert PDF_TOOLS <= set(agent_core.REGISTRY.tool_map)


def test_form_filler_is_gone():
    names = {t["function"]["name"] for t in agent_core.REGISTRY.schemas}
    assert not any(n.startswith("fill_form") for n in names)
    assert "form-scan" not in agent_core.rt.ALLOWED


def test_member_always_injected():
    for tool in PDF_TOOLS:
        out = agent_core.REGISTRY.arguments(tool, {"member": "Wenliang", "session": "x"}, agent_core.Caller(member="Jim"))
        assert out["member"] == "Jim"


def test_edit_is_doc_tool_and_outputs_are_fenced():
    assert "edit_pdf" in agent_core.REGISTRY.doc_tools
    import skill_registry
    reg = skill_registry.load()
    assert {"inspect_pdf", "edit_pdf"} <= reg.untrusted_tools


def test_long_timeouts():
    assert agent_core.rt.CLI_TIMEOUTS["pdf-inspect"] >= 120
    assert agent_core.rt.CLI_TIMEOUTS["pdf-edit"] >= 300


def test_doc_tool_outcome_takes_first_line_only(monkeypatch):
    reg = agent_core.REGISTRY
    monkeypatch.setitem(reg.tool_map, "edit_pdf",
                        lambda a: "jim/pdf_edits/x/form_edited.pdf\n警告: 第 2 页溢出")
    out = reg.call("edit_pdf", {}, agent_core.Caller(member="Jim"))
    assert out.docs == ["jim/pdf_edits/x/form_edited.pdf"]


def test_doc_tool_preview_lines_become_images(monkeypatch):
    reg = agent_core.REGISTRY
    monkeypatch.setitem(reg.tool_map, "edit_pdf",
                        lambda a: "a/x.pdf\n预览: a/p.png\nsession=1")
    out = reg.call("edit_pdf", {}, agent_core.Caller(member="Jim"))
    assert out.docs == ["a/x.pdf"]
    assert out.images == ["a/p.png"]


def test_create_pdf_registered():
    reg = agent_core.REGISTRY
    names = {t["function"]["name"] for t in reg.schemas}
    assert "create_pdf" in names and "create_pdf" in reg.tool_map
    assert {"create_pdf"} <= reg.doc_tools & reg.member_locked
    assert "pdf-create" in agent_core.rt.ALLOWED
    assert agent_core.rt.cli_path("pdf-create").parent.name == "PDF_Editor"
    assert agent_core.rt.CLI_TIMEOUTS["pdf-create"] >= 90
    assert "create_pdf" in agent_core._build_system_prompt()


def test_create_pdf_passes_html_by_file(monkeypatch):
    from pathlib import Path
    big = "<p>" + "字" * 40000 + "</p>"
    seen = {}

    def fake_run_cli(cmd, args):
        p = Path(args["html-file"])
        seen.update(cmd=cmd, args=dict(args), path=p, content=p.read_text(encoding="utf-8"))
        return "jim/pdf_creates/x/document.pdf\n预览: jim/pdf_creates/x/preview.png"
    monkeypatch.setattr(agent_core.rt, "run_cli", fake_run_cli)
    out = agent_core.REGISTRY.call("create_pdf", {"html": big, "title": "T", "member": "X"},
                                   agent_core.Caller(member="Jim"))
    assert seen["cmd"] == "pdf-create" and "html" not in seen["args"]
    assert seen["content"] == big and seen["args"]["member"] == "Jim" and seen["args"]["title"] == "T"
    assert not seen["path"].exists()
    assert out.docs == ["jim/pdf_creates/x/document.pdf"]
    assert out.images == ["jim/pdf_creates/x/preview.png"]


def test_system_prompt_describes_one_shot_workflow():
    p = agent_core._build_system_prompt()
    assert "edit_pdf" in p and "inspect_pdf" in p
    assert "一条消息里把缺的值一起问" in p
    assert "一条消息只问一个" not in p
