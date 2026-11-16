# tests/test_wechat_send_failures.py — SDK 丢弃 sendmessage 响应；包装层记 WARNING。
import logging

import pytest
from weixin_ilink import api

import wechat_ilink

MSG = {"to_user_id": "u1", "context_token": "t"}


@pytest.fixture
def wrapped(monkeypatch):
    """假 send_message 返回 box["resp"]；monkeypatch 撤销时还原真函数。"""
    box = {"resp": {}}
    monkeypatch.setattr(api, "send_message", lambda opts, msg: box["resp"])
    wechat_ilink._log_send_failures()
    return box


@pytest.mark.parametrize("resp", [{"ret": -2}, {"errcode": 40001}])
def test_failure_logs_warning(wrapped, caplog, resp):
    wrapped["resp"] = resp
    with caplog.at_level(logging.WARNING, logger="familyassist.wechat"):
        assert api.send_message(None, MSG) is resp
    assert "sendmessage 失败 to=u1" in caplog.text


@pytest.mark.parametrize("resp", [{}, {"ret": 0, "errcode": 0}])
def test_success_no_warning(wrapped, caplog, resp):
    wrapped["resp"] = resp
    with caplog.at_level(logging.WARNING, logger="familyassist.wechat"):
        assert api.send_message(None, MSG) is resp
    assert not caplog.records


@pytest.mark.parametrize("resp", [None, [1], "ok"])
def test_non_dict_passthrough(wrapped, resp):
    wrapped["resp"] = resp
    assert api.send_message(None, MSG) is resp


def test_wrap_idempotent(wrapped):
    first = api.send_message
    wechat_ilink._log_send_failures()
    assert api.send_message is first
