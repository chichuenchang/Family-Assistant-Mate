# tests/test_browser_guard.py — 付款/下单/本地地址/密码框拦截（代码闸门，不靠提示词）
import pytest

import browser_guard as g


@pytest.mark.parametrize("label", [
    "支付 ¥1,234.00", "立即购买", " PAY NOW ", "Place  your order", "Buy Now", "提交订单",
    "去结算(3)", "Reserve", "预订", "Ｐａｙ", "Proceed to checkout →", "I'll reserve", "￥99 立即支付",
    "现在购买", "去结账", "马上支付"])
def test_order_labels_refused(label):
    assert g.check_click(label)


@pytest.mark.parametrize("label", [
    "Check-out", "Check-out date", "酒店预订", "Booking.com", "我的订单", "加入购物车", "Add to cart",
    "搜索", "Search flights", "支付方式说明", "Paypal accepted here", ""])
def test_navigation_labels_allowed(label):
    assert g.check_click(label) == ""


@pytest.mark.parametrize("url", [
    "file:///C:/Users/x/a.txt", "chrome://settings", "javascript:alert(1)",
    "http://127.0.0.1:9333/json", "http://localhost/", "http://192.168.1.1/", "http://[::1]/",
    "http://0.0.0.0:9333/", "https://cashier.alipay.com/x", "https://www.paypal.com/checkoutnow",
    "https://shop.example.com/checkout/step1", "https://pay.jd.com/", "not a url", ""])
def test_navigate_refused(url):
    assert g.check_navigate(url)


@pytest.mark.parametrize("url", [
    "https://www.google.com/search?q=pay", "https://flights.ctrip.com/",
    "https://www.booking.com/hotel/x.html", "https://www.bestbuy.com/site/gpu",
    "http://example.com/blog/paying-less"])
def test_navigate_allowed(url):
    assert g.check_navigate(url) == ""


def test_type_refusals():
    assert g.check_type("password", "", "")
    assert g.check_type("text", "cc-number", "")
    assert g.check_type("text", "one-time-code", "")
    assert g.check_type("tel", "", "cardNumber")
    assert g.check_type("text", "", "验证码")


def test_type_allowed():
    assert g.check_type("search", "", "q") == ""
    assert g.check_type("text", "name", "passenger") == ""
