"""google_oauth.GoogleAccount：凭据、token 刷新缓存、带认证调用。HTTP 出口 google_oauth._http 打桩。"""
import json

import pytest

import google_oauth
from google_oauth import GoogleAccount, GoogleApiError, GoogleAuthError

PREFIX = "TESTACCT"


@pytest.fixture
def http(monkeypatch):
    for v in ("CLIENT_ID", "CLIENT_SECRET", "REFRESH_TOKEN"):
        monkeypatch.setenv(f"{PREFIX}_{v}", v.lower())
    calls, replies = [], []

    def fake(method, url, data=None, headers=None, timeout=None):
        calls.append({"method": method, "url": url, "data": data,
                      "headers": headers or {}, "timeout": timeout})
        return replies.pop(0)

    monkeypatch.setattr(google_oauth, "_http", fake)
    return calls, replies


def _token_reply(access="A1", expires_in=3600):
    return 200, json.dumps({"access_token": access, "expires_in": expires_in}).encode()


def test_is_configured_needs_all_three_vars(monkeypatch, http):
    assert GoogleAccount(PREFIX).is_configured()
    monkeypatch.delenv(f"{PREFIX}_REFRESH_TOKEN")
    assert not GoogleAccount(PREFIX).is_configured()
    assert not GoogleAccount("NOSUCHPREFIX").is_configured()


def test_token_refreshes_once_then_caches(http):
    calls, replies = http
    replies.append(_token_reply())
    acct = GoogleAccount(PREFIX, timeout=7)
    assert acct.token() == "A1" and acct.token() == "A1"
    assert len(calls) == 1
    assert calls[0]["url"] == google_oauth.TOKEN_URL and calls[0]["timeout"] == 7
    assert b"refresh_token=refresh_token" in calls[0]["data"]


def test_token_refreshes_again_inside_last_minute(http):
    calls, replies = http
    replies += [_token_reply("A1", expires_in=30), _token_reply("A2")]
    acct = GoogleAccount(PREFIX)
    assert acct.token() == "A1"
    assert acct.token() == "A2"      # 30s 有效 < 60s 余量 → 立即视为过期


def test_token_failure_raises_with_status(http):
    _, replies = http
    replies.append((404, b'{"error":"invalid_grant"}'))
    with pytest.raises(GoogleAuthError, match="token 刷新失败") as e:
        GoogleAccount(PREFIX).token()
    assert e.value.status == 404
    assert not isinstance(e.value, GoogleApiError)   # API 404 分流不得吞授权失败


def test_accounts_do_not_share_tokens(http):
    _, replies = http
    replies += [_token_reply("A1"), _token_reply("B1")]
    assert GoogleAccount(PREFIX).token() == "A1"
    assert GoogleAccount(PREFIX).token() == "B1"


def test_json_sends_bearer_and_body(http):
    calls, replies = http
    replies += [_token_reply(), (200, b'{"ok": true}')]
    assert GoogleAccount(PREFIX).json("POST", "https://x/y", {"名": "值"}) == {"ok": True}
    call = calls[1]
    assert call["headers"]["Authorization"] == "Bearer A1"
    assert call["headers"]["Content-Type"] == "application/json"
    assert json.loads(call["data"]) == {"名": "值"}


def test_json_empty_body_is_empty_dict(http):
    _, replies = http
    replies += [_token_reply(), (204, b"")]
    assert GoogleAccount(PREFIX).json("DELETE", "https://x/y") == {}


def test_json_error_carries_status_body_and_label(http):
    _, replies = http
    replies += [_token_reply(), (403, b"insufficient scope")]
    with pytest.raises(GoogleApiError, match="Drive API GET") as e:
        GoogleAccount(PREFIX, label="Drive").json("GET", "https://x/y")
    assert e.value.status == 403 and e.value.body == b"insufficient scope"


def test_json_error_omits_query_string(http):
    _, replies = http
    replies += [_token_reply(), (500, b"{}")]
    with pytest.raises(GoogleApiError) as e:
        GoogleAccount(PREFIX).json("GET", "https://x/messages?q=from%3Adoctor")
    assert "/messages" in str(e.value) and "doctor" not in str(e.value)


def test_request_returns_raw_status_without_raising(http):
    calls, replies = http
    replies += [_token_reply(), (404, b"gone")]
    assert GoogleAccount(PREFIX).request("GET", "https://x/y", headers={"X": "1"}) == (404, b"gone")
    assert calls[1]["headers"] == {"Authorization": "Bearer A1", "X": "1"}
