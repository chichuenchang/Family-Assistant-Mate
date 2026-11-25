"""Any_Search 的 Agent manifest（契约见 Agent_Runtime/skill_registry.py）。"""

from __future__ import annotations


from anysearch import AVAILABLE_DOMAINS
from tool_runtime import fn, s, int_

ORDER = 80

COMMANDS = {"any-search", "any-extract", "any-subdomains"}

TOOLS = {
    "anysearch_search": "any-search",
    "anysearch_extract": "any-extract",
    "anysearch_subdomains": "any-subdomains",
}

UNTRUSTED_TOOLS = {"anysearch_search", "anysearch_extract"}

SCHEMAS = [
    fn("anysearch_search", "AnySearch 垂直领域结构化搜索（finance/health/academic/travel/code 等）。"
       "普通联网查询用 web_search（已含 AnySearch 中英双语），只有需要垂直结构化结果时才用它："
       "先用 anysearch_subdomains 拿到 sub_domain 再传 domain/sub_domain。"
       "返回结果原文，你据此用用户的语言总结", {
        "query": s("搜索关键词/问题"),
        "domain": s("垂直领域（必填；通用查询走 web_search）",
                    enum=[d for d in AVAILABLE_DOMAINS if d != "general"]),
        "sub_domain": s("子域路由键（如 finance.quote），垂直搜索时配 domain；先用 anysearch_subdomains 发现"),
        "sub_domain_params": s("子域参数，key=value,key2=value2 或 JSON（schema 见 anysearch_subdomains 输出）"),
        "max_results": int_("返回结果数 1-10（默认 10）"),
    }, ["query", "domain"]),
    fn("anysearch_extract", "抓取并提取一个网页链接的全文（AnySearch，markdown）。"
       "用户发链接让看/总结、或搜索摘要不够需读全文时用。返回正文，你据此总结", {
        "url": s("网页 URL"),
    }, ["url"]),
    fn("anysearch_subdomains", "查某垂直领域的可用子域及参数 schema（垂直 anysearch_search 前的发现步骤）。"
       "返回 domain/sub_domain/query_format/params_schema 表", {
        "domains": s("单个或逗号分隔的多个领域，如 finance 或 finance,health"),
    }, ["domains"]),
]

PROMPT_RULES = [
    "联网工具返回抓取到的原文，你据此总结；一个来源失败可换另一个，都没查到就如实说，别编造",
    "发图/发文件类工具（visualize_data、edit_pdf、send_file 等）结果自动送达用户，回复里不贴链接或路径",
]
