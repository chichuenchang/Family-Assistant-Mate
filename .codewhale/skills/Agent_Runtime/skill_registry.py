"""发现并合并各 skill 的 agent_tools.py（manifest）。

manifest 是普通模块，模块级属性即契约（全部可选，缺省为空）：
    ORDER           int   合并顺序（prompt 段落 / schema 顺序），默认 100
    COMMANDS        set   本 skill cli.py 的子命令（路由用，含 Agent 不可调的）
    AGENT_COMMANDS  set   Agent 可调子集；缺省 = COMMANDS
    CLI_TIMEOUTS    dict  子命令 → 秒
    TOOLS           dict  工具名 → callable(args)->str，或 str（纯透传的 cli 子命令）
    SCHEMAS         list  工具 JSON schema（tool_runtime.fn 构造；kebab 参数名对模型显示为 snake_case，派发前换回）
    MEMBER_LOCKED   set   剥离 LLM 给的 member、注入发送者（写入 / 按成员私有）
    CONTEXT_TOOLS   set   注入 __channel/__user（异步回推）
    UNTRUSTED_TOOLS set   结果含非本地来源文本（网页/OCR/远程日历）→ 套 tool_runtime.fence 才进 LLM
    IMAGE_TOOLS     set   成功返回 = 图片相对路径，每行一张（传输层发图）
    DOC_TOOLS       set   成功返回首行 = 文件相对路径（传输层发文件）；"预览: <路径>" 行 = 附图
    SHOW_TOOLS      set   成功返回原文由代码附在回复末尾（用户必看到，LLM 藏不了/改不了）
    PROMPT_SECTIONS list[str]  system prompt 独立段落（"## 标题" 开头）
    PROMPT_RULES    list[str]  并入 "## 行为准则" 的条目（不带 "- "）
    CONTEXT_FNS     list[callable(member)->str]  每条消息注入 system prompt 的动态块（数据行含非本地来源 → 自行 fence，标题留在围栏外）
    IMAGE_ROUTES    list[str]  来图/PDF OCR 后的分流条目（agent_core.handle_image 按 ORDER 编号拼接）
    MESSAGE_TICKS   list[callable()]  已注册成员每条消息到达时跑（节流自理）
    SLOW_TICKS      list[callable(push_text, channel)]  后台慢拍（~10 分钟）：提醒/备份
    FAST_TICKS      list[callable(push_text, channel)]  后台快拍（~20 秒）：异步结果投递

新增 skill = 在其目录放 agent_tools.py；agent_core 零改动。
"""

from __future__ import annotations

import importlib.util
import logging
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Callable

import bootstrap
import context_budget as _budget
import tool_runtime as rt

log = logging.getLogger("fam.agent")
MANIFEST_NAME = "agent_tools.py"
ERROR_PREFIX = "[错误]"     # 工具返回以此开头 = 失败（各 skill 统一约定）
PREVIEW_PREFIX = "预览:"    # DOC_TOOLS 结果里的附图行


@dataclass(frozen=True)
class Caller:
    """谁在调工具。全部由代码解析（传输层闸门 / Agent 轮次），LLM 给不了也改不了。"""
    member: str = ""     # members.resolve 解析出的成员名
    channel: str = ""    # 发起频道（异步回推路由）
    user: str = ""       # 频道内用户 id
    turn_id: int = 0     # 该用户本轮序号（两轮确认闸门）
    said: str = ""       # 用户本人亲手打的字（确认闸门只认它）


@dataclass
class ToolOutcome:
    """一次工具调用的结果，已按 manifest 声明处理完。"""
    for_llm: str                 # 本轮回给 LLM（UNTRUSTED_TOOLS 已套围栏）
    for_history: str              # 跨轮存档（先截断再套围栏：反过来闭合标记会被截掉）
    images: list[str] = field(default_factory=list)   # IMAGE_TOOLS 成功产出的 data 相对路径
    docs: list[str] = field(default_factory=list)     # DOC_TOOLS 成功产出的 data 相对路径
    shown: str = ""               # SHOW_TOOLS 成功原文（必达用户）


@dataclass
class Registry:
    modules: dict[str, ModuleType] = field(default_factory=dict)   # skill 目录名 → manifest
    tool_map: dict[str, Callable] = field(default_factory=dict)
    schemas: list[dict] = field(default_factory=list)
    member_locked: set[str] = field(default_factory=set)
    context_tools: set[str] = field(default_factory=set)
    untrusted_tools: set[str] = field(default_factory=set)
    image_tools: set[str] = field(default_factory=set)
    doc_tools: set[str] = field(default_factory=set)
    show_tools: set[str] = field(default_factory=set)
    prompt_sections: list[str] = field(default_factory=list)
    prompt_rules: list[str] = field(default_factory=list)
    context_fns: list[Callable[[str], str]] = field(default_factory=list)
    image_routes: list[str] = field(default_factory=list)
    message_ticks: list[Callable] = field(default_factory=list)
    slow_ticks: list[Callable] = field(default_factory=list)
    fast_ticks: list[Callable] = field(default_factory=list)

    def context(self, member: str) -> str:
        """全部动态块拼接；单块失败只记日志，绝不拖垮 handle()。"""
        out = []
        for f in self.context_fns:
            try:
                out.append(f(member) or "")
            except Exception:
                log.exception("上下文注入失败（已跳过）: %s", getattr(f, "__name__", f))
        return "".join(out)

    def arguments(self, name: str, args: dict, caller: Caller) -> dict:
        """LLM 给的参数 → 工具真正收到的参数。
        kebab 键名换回；MEMBER_LOCKED 剥掉 LLM 给的 member、注入 caller.member（不得跨成员）；
        CONTEXT_TOOLS 另注入 __channel/__user/__turn_id/__text。其余工具原样放行。"""
        args = rt.to_manifest_keys(name, args)
        if name in self.member_locked:
            args = {k: v for k, v in args.items() if k.lstrip("-") != "member"}
            if caller.member:
                args["member"] = caller.member
        if name in self.context_tools:
            args = {**args, "__channel": caller.channel or "",
                    "__user": str(caller.user) if caller.user else "",
                    "__turn_id": int(caller.turn_id), "__text": caller.said}
            if caller.member:
                args["member"] = caller.member
        return args

    def call(self, name: str, args: dict, caller: Caller) -> ToolOutcome:
        """执行一次工具调用：参数注入 → 调用 → 判成败 → 收产出文件 → 套围栏/截断。"""
        fn = self.tool_map.get(name)
        args = self.arguments(name, args, caller)
        result = fn(args) if fn else f"{ERROR_PREFIX} 未知工具: {name}"
        log.debug("工具 %s(%s) → %s", name,
                  ", ".join(f"{k}={v}" for k, v in args.items()), result[:200])
        ok = bool(result) and not result.startswith(ERROR_PREFIX)
        fence = (lambda t: rt.fence(t, name)) if name in self.untrusted_tools else (lambda t: t)
        out = ToolOutcome(fence(result), fence(_budget.clip_tool_result(result)))
        if not ok:
            return out
        if name in self.image_tools:
            # 每行一张（fetch_images 多张）；按行不按空白拆——路径可含空格
            out.images = [ln.strip() for ln in result.splitlines() if ln.strip()]
        elif name in self.doc_tools:
            # 首行是路径，后续可能有"警告:"行——只取首行；"预览:"行另作图发
            lines = result.strip().splitlines()
            out.docs = [lines[0]]
            out.images = [ln.split(":", 1)[1].strip() for ln in lines[1:]
                          if ln.startswith(PREVIEW_PREFIX)]
        if name in self.show_tools:
            out.shown = result
        return out


def run_ticks(fns: list[Callable], *args) -> None:
    """逐个跑节拍钩子；单个失败只记日志，不影响其余。"""
    for f in fns:
        try:
            f(*args)
        except Exception:
            log.exception("节拍钩子异常（已跳过）: %s", getattr(f, "__name__", f))


def _import_manifest(skill: str, path) -> ModuleType:
    # 模块名带 skill 前缀：多个目录同名 agent_tools.py，不能撞 sys.modules
    spec = importlib.util.spec_from_file_location(f"agent_tools_{skill}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def discover() -> list[tuple[Path, ModuleType]]:
    found = []
    for d in bootstrap.skill_dirs():
        p = d / MANIFEST_NAME
        if p.exists():
            found.append((d, _import_manifest(d.name, p)))
    found.sort(key=lambda kv: (getattr(kv[1], "ORDER", 100), kv[0].name))
    return found


def load() -> Registry:
    """重建 tool_runtime 的命令表并返回合并后的 Registry（可重复调用，幂等）。"""
    reg = Registry()
    rt.ALLOWED.clear()
    rt.COMMAND_DIR.clear()
    rt.CLI_TIMEOUTS.clear()
    for skill_dir, m in discover():
        skill = skill_dir.name
        reg.modules[skill] = m
        commands = set(getattr(m, "COMMANDS", ()))
        for c in commands:
            rt.COMMAND_DIR[c] = skill_dir
        rt.ALLOWED |= set(getattr(m, "AGENT_COMMANDS", commands))
        rt.CLI_TIMEOUTS.update(getattr(m, "CLI_TIMEOUTS", {}))
        for name, impl in getattr(m, "TOOLS", {}).items():
            if name in reg.tool_map:
                raise RuntimeError(f"工具重名: {name}（{skill}）")
            reg.tool_map[name] = rt.cli_tool(impl) if isinstance(impl, str) else impl
        reg.schemas.extend(getattr(m, "SCHEMAS", ()))
        reg.member_locked |= set(getattr(m, "MEMBER_LOCKED", ()))
        reg.context_tools |= set(getattr(m, "CONTEXT_TOOLS", ()))
        reg.untrusted_tools |= set(getattr(m, "UNTRUSTED_TOOLS", ()))
        reg.image_tools |= set(getattr(m, "IMAGE_TOOLS", ()))
        reg.doc_tools |= set(getattr(m, "DOC_TOOLS", ()))
        reg.show_tools |= set(getattr(m, "SHOW_TOOLS", ()))
        reg.prompt_sections.extend(getattr(m, "PROMPT_SECTIONS", ()))
        reg.prompt_rules.extend(getattr(m, "PROMPT_RULES", ()))
        reg.context_fns.extend(getattr(m, "CONTEXT_FNS", ()))
        reg.image_routes.extend(getattr(m, "IMAGE_ROUTES", ()))
        reg.message_ticks.extend(getattr(m, "MESSAGE_TICKS", ()))
        reg.slow_ticks.extend(getattr(m, "SLOW_TICKS", ()))
        reg.fast_ticks.extend(getattr(m, "FAST_TICKS", ()))
    return reg
