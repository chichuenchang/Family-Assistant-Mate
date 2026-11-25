"""Browser_Agent 的 Agent manifest（契约见 Agent_Runtime/skill_registry.py）。

browse：后台浏览任务（browser_jobs）；截图途中经 MEDIA_TICKS 推送，报告完成后推送。
browse_stop：停发起人自己的任务。两者都由代码注入 __channel/__user/member，LLM 改不了投递目标。
"""

from __future__ import annotations

import importlib.util

import browser_jobs
from tool_runtime import fn, s

ORDER = 75

COMMANDS = {"browser-login"}
AGENT_COMMANDS: set[str] = set()     # 登录只在电脑上由人操作


def tool_browse(args):
    channel, user = args.get("__channel", ""), args.get("__user", "")
    if not (channel and user):
        return "[错误] browse 仅在微信/Telegram 频道可用"
    task = (args.get("task") or "").strip()
    if not task:
        return "[错误] 缺少任务内容"
    if importlib.util.find_spec("playwright") is None:
        return "[错误] 缺 playwright：在电脑上运行 pip install playwright"
    _jid, msg = browser_jobs.submit(task, channel, user, args.get("member", ""))
    return msg


def tool_browse_stop(args):
    return browser_jobs.stop(args.get("__channel", ""), args.get("__user", ""))


TOOLS = {"browse": tool_browse, "browse_stop": tool_browse_stop}
CONTEXT_TOOLS = MEMBER_LOCKED = {"browse", "browse_stop"}
MEDIA_TICKS = [browser_jobs.deliver]
CONTEXT_FNS = [browser_jobs.last_report]

SCHEMAS = [
    fn("browse", "用电脑上的真实浏览器替用户办事：跨平台比价（机票/酒店/商品）、看地图、找图片、"
       "打开并操作任意网站。后台运行数分钟，截图和结果自动发给用户——你只需把本工具返回的提示原样转达，"
       "不要等待、不要编造结果。只查不买：不付款、不下单。", {
        "task": s("完整任务，自成一体：要查什么、日期/人数/预算/型号、用户点名的平台、要不要截图。"
                  "浏览器助手看不到对话，缺的信息它无从得知"),
    }, ["task"]),
    fn("browse_stop", "停止用户正在进行的浏览任务，已查到的部分会发给用户", {}),
]

PROMPT_RULES = [
    "browse：比价、看地图、找图片、“打开/看看某网站”，或 web_search 返回 [错误] 时用；"
    "查事实、新闻仍先用 web_search。任务信息不全先问用户再调",
    "“最近一次浏览任务”块是 browse 的结果；用户接着说“第二个”“加购物车”之类，带上该结果里的链接和细节再调 browse",
]
