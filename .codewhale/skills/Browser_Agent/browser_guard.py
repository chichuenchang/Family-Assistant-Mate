"""付款闸门（代码执行，不靠提示词）。设计：docs/superpowers/specs/2026-11-25-browser-agent-design.md「Payment guard」。

每个函数返回 "" = 放行，否则拦截理由。按钮按**整句**匹配（归一化后）：子串匹配会把
「Check-out 日期」「酒店预订」标签页也拦掉，比价就做不成。代价：少见的付款按钮措辞会漏过。
"""

from __future__ import annotations

import ipaddress
import re
import unicodedata
from urllib.parse import urlsplit

ORDER_LABELS = frozenset("""
支付 去支付 立即支付 确认支付 付款 去付款 立即付款 确认付款 提交订单 确认订单 确认下单 下单 立即下单 去下单
购买 立即购买 马上购买 立即抢购 确认购买 结算 去结算 立即结算 预订 立即预订 马上预订 确认预订 预定 立即预定
订 立即订 订购 立即订购 同意并支付 同意并提交
现在购买 现在支付 现在付款 现在预订 马上支付 马上付款 结账 去结账 立即结账
""".split()) | frozenset([
    "pay", "pay now", "place order", "place your order", "submit order", "confirm order",
    "complete order", "order now", "buy now", "buy it now", "purchase", "complete purchase",
    "confirm purchase", "checkout", "proceed to checkout", "go to checkout", "continue to checkout",
    "secure checkout", "book", "book now", "reserve", "reserve now", "ill reserve",
    "complete booking", "confirm booking", "confirm and pay", "continue to payment",
    "proceed to payment", "subscribe", "start free trial",
])

_PAY_HOST_LABELS = {"pay", "cashier", "pcashier", "excashier", "mcashier", "payment", "payments", "checkout"}
_PAY_HOST_SUFFIXES = ("paypal.com", "tenpay.com")
_PAY_PATH_SEGMENTS = {"pay", "payment", "payments", "cashier", "checkout", "placeorder"}

_MONEY = re.compile(r"(?:us)?[¥￥$€£]\s*[\d.,]+")
_TRAILING_NUM = re.compile(r"(?:\s+\d+)+$")
_SECRET_NAME = re.compile(r"(?i)card|cvv|cvc|passw|卡号|密码|验证码")
_SECRET_AUTOCOMPLETE = {"current-password", "new-password", "one-time-code"}


def normalize_label(label: str) -> str:
    s = unicodedata.normalize("NFKC", label or "").lower()
    s = _MONEY.sub(" ", s)
    s = re.sub(r"['’]", "", s)
    s = re.sub(r"[\W_]+", " ", s).strip()
    return _TRAILING_NUM.sub("", s).strip()


def check_click(label: str) -> str:
    if normalize_label(label) in ORDER_LABELS:
        return f"不替用户付款/下单/预订：按钮「{(label or '').strip()}」留给用户本人点"
    return ""


def _local_host(host: str) -> bool:
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_unspecified


def check_navigate(url: str) -> str:
    try:
        parts = urlsplit((url or "").strip())
        host = (parts.hostname or "").lower()
    except ValueError:
        return "网址无效"
    if parts.scheme not in ("http", "https") or not host:
        return "只能打开 http/https 网页"
    if _local_host(host):
        return "不访问本机或局域网地址"
    if (set(host.split(".")) & _PAY_HOST_LABELS
            or any(host == s or host.endswith("." + s) for s in _PAY_HOST_SUFFIXES)):
        return f"{host} 是付款页面，留给用户本人处理"
    if {seg.lower() for seg in parts.path.split("/")} & _PAY_PATH_SEGMENTS:
        return "这是付款/结算页面，留给用户本人处理"
    return ""


def check_type(input_type: str, autocomplete: str, name: str) -> str:
    ac = (autocomplete or "").lower()
    if ((input_type or "").lower() == "password" or ac.startswith("cc-")
            or ac in _SECRET_AUTOCOMPLETE or _SECRET_NAME.search(name or "")):
        return "不输入密码、验证码或银行卡信息"
    return ""
