"""Google 账号：凭据、access token、带认证的调用（各 Google provider 共用）。

GoogleAccount(prefix)：凭据只从 os.environ（含 .codewhale/.env，见 project_env）<prefix>_CLIENT_ID / _CLIENT_SECRET / _REFRESH_TOKEN 读；
refresh token 换 access token 并缓存到过期前 1 分钟（每实例一份）。
run_loopback_auth：一次性授权（各 provider 的 --auth）。本地回环 OAuth：起临时 http 服务接 code，
浏览器里用户批准，换 refresh token，写入 .codewhale/.env。
_http 是全部 Google 流量的唯一出口（测试在此打桩）。
"""

from __future__ import annotations

import http.server
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DEFAULT_TIMEOUT = 60
_CRED_VARS = ("CLIENT_ID", "CLIENT_SECRET", "REFRESH_TOKEN")
_FORM = {"Content-Type": "application/x-www-form-urlencoded"}


class GoogleApiError(RuntimeError):
    """Google API 返回 ≥300。status / body 供调用方按码分流。"""

    def __init__(self, status: int, msg: str, body: bytes = b""):
        super().__init__(msg)
        self.status = status
        self.body = body


class GoogleAuthError(RuntimeError):
    """refresh token 换 access token 失败。不是 GoogleApiError：调用方按 API 码分流
    （如 404 略过）时不得误吞授权失败。"""

    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status = status


def _http(method: str, url: str, data: bytes | None = None,
          headers: dict | None = None, timeout: int = DEFAULT_TIMEOUT) -> tuple[int, bytes]:
    """唯一 HTTP 出口（测试在此打桩）。返回 (status, body)，HTTP 错误不抛。"""
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class GoogleAccount:
    """一组 Google OAuth 凭据（环境变量前缀 prefix）及其 access token。

    timeout = 单次 HTTP 上限秒数；label 只进错误文本（"Gmail" / "Drive"）。
    """

    def __init__(self, prefix: str, *, timeout: int = DEFAULT_TIMEOUT, label: str = "Google"):
        self.prefix = prefix
        self.timeout = timeout
        self.label = label
        self._access = ""
        self._exp = 0.0

    def _env(self, suffix: str) -> str:
        return os.environ.get(f"{self.prefix}_{suffix}", "")

    def is_configured(self) -> bool:
        """三个环境变量齐备即视为已配置。"""
        return all(self._env(v) for v in _CRED_VARS)

    def token(self) -> str:
        """access token；过期前 1 分钟内重新用 refresh token 换。"""
        if self._access and time.time() < self._exp:
            return self._access
        data = urllib.parse.urlencode({
            "client_id": self._env("CLIENT_ID"),
            "client_secret": self._env("CLIENT_SECRET"),
            "refresh_token": self._env("REFRESH_TOKEN"),
            "grant_type": "refresh_token",
        }).encode()
        status, body = _http("POST", TOKEN_URL, data, _FORM, self.timeout)
        if status != 200:
            raise GoogleAuthError(status, f"Google OAuth token 刷新失败 {status}: {body[:200]!r}")
        tok = json.loads(body)
        self._access = tok["access_token"]
        self._exp = time.time() + int(tok.get("expires_in", 3600)) - 60
        return self._access

    def request(self, method: str, url: str, data: bytes | None = None,
                headers: dict | None = None) -> tuple[int, bytes]:
        """带认证的原始调用（上传/下载等非 JSON 场景）。返回 (status, body)，不判状态码。"""
        headers = {"Authorization": f"Bearer {self.token()}", **(headers or {})}
        return _http(method, url, data, headers, self.timeout)

    def json(self, method: str, url: str, payload: dict | None = None) -> dict:
        """带认证的 JSON 调用。≥300 → GoogleApiError；空响应体 → {}。
        错误文本只带 URL 路径：查询串含邮件搜索词等用户内容，不进日志。"""
        data, headers = None, {}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode()
            headers["Content-Type"] = "application/json"
        status, body = self.request(method, url, data, headers)
        if status >= 300:
            raise GoogleApiError(
                status, f"{self.label} API {method} {urllib.parse.urlsplit(url).path} → {status}: "
                        f"{body[:200]!r}", body)
        return json.loads(body) if body else {}


def run_loopback_auth(prefix: str, scope: str, *, consent: str, next_step: str,
                      client_hint: str = "") -> None:
    """consent：授权页权限说明；next_step：成功后提示；client_hint：OAuth 客户端补充说明。"""
    client_id = os.environ.get(f"{prefix}_CLIENT_ID", "")
    client_secret = os.environ.get(f"{prefix}_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        print(f"先在 .codewhale/.env 填 {prefix}_CLIENT_ID / {prefix}_CLIENT_SECRET"
              f"（Google Cloud Console → OAuth 客户端，Desktop app 类型{client_hint}），"
              "然后重跑。")
        raise SystemExit(1)

    code_holder: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            code_holder["code"] = (qs.get("code") or [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<h2>授权完成，可以关掉这个页面回到终端。</h2>".encode())

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    redirect = f"http://127.0.0.1:{port}"
    threading.Thread(target=server.handle_request, daemon=True).start()

    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect,
        "response_type": "code",
        "scope": scope,
        "access_type": "offline",
        "prompt": "consent",
    })
    print(f"浏览器即将打开 Google 授权页（{consent}）…")
    print(f"没自动打开就手动访问：\n{url}\n")
    webbrowser.open(url)

    print("等待授权回调…")
    deadline = time.time() + 300
    while "code" not in code_holder and time.time() < deadline:
        time.sleep(0.5)
    server.server_close()
    code = code_holder.get("code")
    if not code:
        print("5 分钟内未收到授权回调，重跑 --auth 再试。")
        raise SystemExit(1)

    data = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect,
    }).encode()
    status, body = _http("POST", TOKEN_URL, data, _FORM)
    if status != 200:
        print(f"换取 token 失败 {status}: {body[:300]!r}")
        raise SystemExit(1)
    refresh = json.loads(body).get("refresh_token", "")
    if not refresh:
        print("响应里没有 refresh_token（多半是之前授权过且未带 prompt=consent）。"
              "去 https://myaccount.google.com/permissions 移除本应用授权后重跑。")
        raise SystemExit(1)

    import project_env
    path = project_env.set_key(f"{prefix}_REFRESH_TOKEN", refresh)
    print(f"\n授权成功：{prefix}_REFRESH_TOKEN 已写入 {path}")
    print(f"\n{next_step}")
