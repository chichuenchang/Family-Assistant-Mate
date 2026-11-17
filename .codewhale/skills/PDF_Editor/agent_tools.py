"""PDF_Editor 的 Agent manifest（契约见 Agent_Runtime/skill_registry.py）。

编辑会话按成员私有（data/<成员>/pdf_edits/），一律强制注入发送者 member。
pdf-edit = 渲染/OCR + 排版 LLM（至多两次 120s 调用）+ 重组 PDF：超时给足。
create_pdf 不进 UNTRUSTED_TOOLS：输出只有自家路径/提示，不含外部文本。
"""

from __future__ import annotations

import os
import tempfile

import tool_runtime as rt
from tool_runtime import fn, s

ORDER = 95

COMMANDS = {"pdf-inspect", "pdf-edit", "pdf-list", "pdf-pages", "pdf-create"}
CLI_TIMEOUTS = {"pdf-inspect": 120, "pdf-edit": 300, "pdf-create": 90}


def tool_create_pdf(args):
    """HTML 走临时文件交 CLI：整页 HTML 常超 Windows 命令行 32767 字符上限。"""
    args = dict(args)
    html = str(args.pop("html", "") or "")
    fd, tmp = tempfile.mkstemp(suffix=".html", prefix="fam_create_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(html)
        return rt.run_cli("pdf-create", {**args, "html-file": tmp})
    finally:
        os.unlink(tmp)


TOOLS = {
    "inspect_pdf": "pdf-inspect",
    "edit_pdf": "pdf-edit",
    "pdf_edit_list": "pdf-list",
    "pdf_pages": "pdf-pages",
    "create_pdf": tool_create_pdf,
}

MEMBER_LOCKED = set(TOOLS)
DOC_TOOLS = {"edit_pdf", "create_pdf"}
UNTRUSTED_TOOLS = {"inspect_pdf", "edit_pdf"}   # 来件 PDF 的字段/OCR 文本、排版模型转述

SCHEMAS = [
    fn("inspect_pdf", "看一份 PDF 是什么类型、几页、里面要填什么（表单字段或各页文字）。"
       "不知道这份表要哪些信息时先调它，再向用户要值。", {
        "file": s("PDF 路径（用户发来的保存路径，data 内）"),
    }, ["file"]),
    fn("pdf_pages", "只查一份 PDF 总共几页（快，不建编辑会话、不 OCR）。只要页数时用它，别用 inspect_pdf。", {
        "file": s("PDF 路径（用户发来的保存路径，data 内）"),
    }, ["file"]),
    fn("edit_pdf", "按一句指令编辑 PDF 并自动把结果发给用户：填表单、在任意位置写字、打勾、"
       "白底盖掉原内容再改写、贴签名/图片、画线、删页/旋转/重排/合并另一份 PDF。"
       "首次传 file；用户要更正结果时传上次返回的 session + 只说更正内容。", {
        "file": s("PDF 路径（首次编辑时传）"),
        "session": s("上次 edit_pdf 返回的 session（续改时传；不确定就 pdf_edit_list 查，别自己编）"),
        "instruction": s("要做的全部编辑，一句话写全，值必须是用户给的原话。"
                         "例：\"姓名填 张三；出生日期 1990-01-02；婚姻状况勾 已婚；"
                         "第 2 页签名处贴 Jim/inbox/2026-09/sig.png；删掉第 4 页\""),
        "fresh": rt.boolean("true = 丢开这份 PDF 之前的编辑，从原件重新开始"),
    }, ["instruction"]),
    fn("pdf_edit_list", "列出我的 PDF 编辑会话（找回 session 续改用）。", {}),
    fn("create_pdf", "从零做一份新 PDF（传单、合同、通知、表格、海报等）：你写整页 HTML/CSS，"
       "工具用浏览器打印成 PDF，并把 PDF 和第 1 页预览图发给用户。改已有 PDF 用 edit_pdf。", {
        "html": s("完整自包含的 HTML 文档（CSS 写在 <style> 里）。@page 设纸张/边距（默认 A4）；"
                  "中文字体 font-family: \"Microsoft YaHei\", \"SimSun\", sans-serif；"
                  "图形用 CSS/内联 SVG；图片只能用 data 内路径（如 <img src=\"Jim/inbox/2026-11/logo.png\">），"
                  "网址图片和 JavaScript 会被去掉；表单 = 画线/方框供手填"),
        "title": s("文件名（不带 .pdf），如 \"租房合同\"；续改不传则沿用"),
        "session": s("上次 create_pdf 返回的 session（修改同一份时传，并传改好的完整 HTML）"),
    }, ["html"]),
]

PROMPT_RULES = [
    "填/改 PDF：不知道表里要什么先 inspect_pdf；**一条消息里把缺的值一起问**，绝不编造值。"
    "没签名图或让你代签 → 用本人姓名手写体签，别推说签不了。全部编辑写进一句 instruction 调 edit_pdf；"
    "更正就带同一 session 只写更正。结果里的 `提示:`/`警告:` 原意转述",
    "做新 PDF（传单/合同/通知等，没有原件）→ create_pdf，内容排版由你定；用户要改就带同一 session "
    "传改好的完整 HTML。用户看到的是 PDF 和预览图，别把 HTML 源码发给用户",
]

IMAGE_ROUTES = [
    "用户要填写或修改这份 PDF → 编辑（不归档）；拿不准归档还是编辑就问",
]
