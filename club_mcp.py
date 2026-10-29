# -*- coding: utf-8 -*-
"""金蝶云社区 MCP 客户端（Streamable HTTP + SSE，**纯标准库**）。

协议要点（照着 MCP 2025-06-18 的 Streamable HTTP 传输实现）
────────────────────────────────────────────────────────
1. 所有消息都是一次 `POST <url>`，`Content-Type: application/json`，
   `Accept: application/json, text/event-stream`；
2. 服务端可能直接回 JSON，也可能回 `text/event-stream` —— 两种都要处理；
3. `initialize` 的响应头可能带 `Mcp-Session-Id`，之后每个请求都要原样带回；
4. 初始化成功后要补一条 `notifications/initialized` 通知（无 id，服务端通常回 202）；
5. 请求靠 `id` 配对；通知没有 `id`，不期待响应。

为什么手写而不用官方 SDK
────────────────────────
`mcp` 这个包依赖 pydantic / anyio / httpx 一串，装不上的内网机器直接废掉；而本技能
只需要「发 JSON、读 JSON/SSE」这一件事。**纯标准库 = 任何 Python 3.8+ 都能跑**，
也正好符合本系列的既定原则（核心链路不引第三方依赖）。

安全
────
令牌只存在内存里：优先命令行参数 → 环境变量 → `clubstore` 的 DPAPI 密文。
本模块不打日志、不回显令牌；异常信息里也只出现服务端返回的文本。
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import socket
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Callable, Optional

import clubstore

DEFAULT_BASE_URL = "https://vip.kingdee.com/api/mcp"
PROTOCOL_VERSION = "2025-06-18"
CLIENT_NAME = "kingdee-club-skill"
CLIENT_VERSION = "1.0.5"
USER_AGENT = f"{CLIENT_NAME}/{CLIENT_VERSION} (+https://littlebeaver.top)"

TOKEN_ENVS = ("KINGDEE_CLUB_TOKEN", "KINGDEE_CLUB_PAT")
BASE_URL_ENV = "KINGDEE_CLUB_MCP_URL"

DEFAULT_TIMEOUT = 60.0
CALL_TIMEOUT = 180.0

_MISSING = object()


# ─────────────────────────── 异常（带退出码语义） ───────────────────────────

class ClubError(Exception):
    """本技能的统一异常基类。`kind` 用来决定 CLI 退出码。"""

    kind = "error"

    def __init__(self, message: str, *, status: int | None = None, detail: str = ""):
        super().__init__(message)
        self.status = status
        self.detail = detail

    def as_dict(self) -> dict:
        return {"kind": self.kind, "message": str(self), "status": self.status, "detail": self.detail}


class TokenMissing(ClubError):
    kind = "token-missing"


class TokenRejected(ClubError):
    kind = "token-rejected"


class TransportError(ClubError):
    kind = "transport"


class ServerError(ClubError):
    kind = "server"


class ProtocolError(ClubError):
    kind = "protocol"


class ToolError(ClubError):
    kind = "tool"


# ─────────────────────────── 令牌 / 地址解析 ───────────────────────────

def _clean(value: str) -> str:
    """去掉所有空白：用户从网页复制令牌经常带换行/空格，而令牌本身不含空白。"""
    return "".join((value or "").split())


def resolve_token(explicit: Optional[str] = None) -> tuple[str, str]:
    """按 参数 → 环境变量 → DPAPI 密文 的顺序取令牌。

    返回 (token, 来源说明)。**来源说明只用于展示，不含令牌本身。**
    """
    if explicit and _clean(explicit):
        return _clean(explicit), "命令行参数"

    for name in TOKEN_ENVS:
        value = os.environ.get(name)
        if value and _clean(value):
            return _clean(value), f"环境变量 {name}"

    data = clubstore.load()
    if data and data.get("token"):
        token = _clean(str(data["token"]))
        if token:
            return token, "加密凭据 club_token.bin（DPAPI）"

    raise TokenMissing(
        "尚未配置金蝶云社区个人令牌。请先运行 `python setup_token.py` "
        "（弹窗录入，Windows DPAPI 加密保存，不写明文）；"
        "或在本次会话里设置环境变量 KINGDEE_CLUB_TOKEN。"
    )


def resolve_base_url(explicit: Optional[str] = None) -> str:
    if explicit:
        url = explicit.strip()
    else:
        url = (os.environ.get(BASE_URL_ENV) or "").strip()
        if not url:
            data = clubstore.load() or {}
            url = str(data.get("base_url") or "").strip()
    url = url or DEFAULT_BASE_URL
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ProtocolError(f"服务地址不合法：{url}（应形如 https://vip.kingdee.com/api/mcp）")
    return url


# ─────────────────────────── 客户端 ───────────────────────────

class McpClient:
    """一个会话 = 一次 initialize + 若干次 tools 调用。"""

    def __init__(self, token: Optional[str] = None, base_url: Optional[str] = None,
                 timeout: float = DEFAULT_TIMEOUT, *, need_token: bool = True):
        self.token = ""
        self.token_source = "（未使用）"
        if token and _clean(token):
            self.token, self.token_source = _clean(token), "命令行参数"
        elif need_token:
            self.token, self.token_source = resolve_token(token)
        self.base_url = resolve_base_url(base_url)
        self.timeout = float(timeout)
        self.session_id: Optional[str] = None
        self.protocol_version: Optional[str] = None
        self.server_info: dict = {}
        self.capabilities: dict = {}
        self._next_id = 1
        self._initialized = False
        self._tools: list | None = None

    # —— 协议层 ——

    def _headers(self) -> dict:
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json, text/event-stream",
            "User-Agent": USER_AGENT,
        }
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        if self._initialized and self.protocol_version:
            headers["MCP-Protocol-Version"] = self.protocol_version
        return headers

    @staticmethod
    def _same_id(a, b) -> bool:
        return a is not None and b is not None and str(a) == str(b)

    def _http_error(self, exc: urllib.error.HTTPError) -> ClubError:
        raw = b""
        try:
            raw = exc.read() or b""
        except Exception:  # noqa: BLE001 - 读错误体失败不该掩盖原始状态码
            pass
        text = raw.decode("utf-8", "replace").strip()
        message = ""
        try:
            payload = json.loads(text)
            if isinstance(payload, dict):
                message = str(payload.get("message") or payload.get("error_description")
                              or payload.get("error") or "")
        except ValueError:
            pass
        detail = (message or text)[:400]

        if exc.code in (401, 403):
            hint = ("令牌无效、已过期，或没有该 MCP 服务的权限。"
                    "请重新运行 `python setup_token.py` 换一个新令牌。")
            return TokenRejected(f"认证失败（HTTP {exc.code}）：{hint}",
                                 status=exc.code, detail=detail)
        if exc.code == 404:
            return ProtocolError(f"服务地址不存在（HTTP 404）：{self.base_url}",
                                 status=404, detail=detail)
        if 500 <= exc.code < 600:
            return ServerError(f"金蝶云社区服务端错误（HTTP {exc.code}），稍后重试。",
                               status=exc.code, detail=detail)
        return ProtocolError(f"请求被拒绝（HTTP {exc.code}）：{detail}", status=exc.code, detail=detail)

    def _transport_error(self, exc: BaseException) -> ClubError:
        reason = getattr(exc, "reason", exc)
        text = str(reason)
        hint = ""
        low = text.lower()
        if isinstance(reason, socket.gaierror) or "getaddrinfo" in low or "name or service" in low:
            hint = "域名解析失败，检查网络/DNS。"
        elif isinstance(reason, ssl.SSLError) or "certificate" in low:
            hint = "TLS 证书校验失败，检查是否有代理或安全软件做了 HTTPS 拦截。"
        elif "timed out" in low or isinstance(reason, socket.timeout):
            hint = "连接超时，检查网络或代理。"
        elif "proxy" in low or "tunnel" in low:
            hint = "代理连接失败：确认系统代理可用，或临时清掉 HTTPS_PROXY 再试。"
        elif "refused" in low:
            hint = "连接被拒绝。"
        return TransportError(f"连接金蝶云社区失败：{text}" + (f"（{hint}）" if hint else ""),
                              detail=text)

    def _parse_message(self, raw: str) -> Optional[dict]:
        if not raw.strip():
            return None
        try:
            msg = json.loads(raw)
        except ValueError:
            return None
        if isinstance(msg, dict) and msg.get("jsonrpc") == "2.0":
            return msg
        return None

    def _consume_sse(self, resp, want_id, on_message) -> Optional[dict]:
        """逐事件解析 SSE，拿到目标 id 的响应就停（之后主动断开这条流）。"""
        buffer: list[str] = []
        found: Optional[dict] = None
        for raw_line in resp:
            line = raw_line.decode("utf-8", "replace").rstrip("\r\n")
            if not line:
                if not buffer:
                    continue
                msg = self._parse_message("\n".join(buffer))
                buffer = []
                if msg is None:
                    continue
                if want_id is not _MISSING and self._same_id(msg.get("id"), want_id):
                    found = msg
                    break
                if on_message:  # 服务端主动推送（日志/进度），转发给上游
                    on_message(msg)
                continue
            if line.startswith(":"):  # 注释/心跳
                continue
            field, _, value = line.partition(":")
            if value.startswith(" "):
                value = value[1:]
            if field == "data":
                buffer.append(value)
        if buffer and found is None:  # 流末尾没有空行收尾
            msg = self._parse_message("\n".join(buffer))
            if msg is not None:
                if want_id is not _MISSING and self._same_id(msg.get("id"), want_id):
                    found = msg
                elif on_message:
                    on_message(msg)
        return found

    def _post(self, payload: dict, *, timeout: Optional[float] = None,
              want_id=_MISSING, on_message: Optional[Callable[[dict], None]] = None) -> Optional[dict]:
        """发一条 JSON-RPC 消息。`want_id` 指定要等哪个响应；通知传 `_MISSING`。"""
        timeout = float(timeout or self.timeout)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.base_url, data=body, method="POST",
                                     headers=self._headers())
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            raise self._http_error(exc) from None
        except urllib.error.URLError as exc:
            raise self._transport_error(exc) from None
        except (socket.timeout, TimeoutError) as exc:
            raise self._transport_error(exc) from None
        except OSError as exc:
            raise self._transport_error(exc) from None

        with resp:
            sid = resp.headers.get("Mcp-Session-Id")
            if sid:
                self.session_id = sid.strip()
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if "text/event-stream" in ctype:
                return self._consume_sse(resp, want_id, on_message)
            try:
                raw = resp.read()
            except (socket.timeout, TimeoutError) as exc:
                raise self._transport_error(exc) from None

        if not raw or not raw.strip():
            return None
        try:
            msg = json.loads(raw.decode("utf-8", "replace"))
        except ValueError as exc:
            raise ProtocolError(f"服务端返回的不是合法 JSON：{raw[:200]!r}") from exc
        if not isinstance(msg, dict):
            raise ProtocolError("服务端返回的 JSON-RPC 消息不是对象")
        if want_id is not _MISSING and self._same_id(msg.get("id"), want_id):
            return msg
        if on_message:
            on_message(msg)
        return msg

    def request(self, method: str, params: Optional[dict] = None,
                *, timeout: Optional[float] = None) -> dict:
        msg_id = self._next_id
        self._next_id += 1
        payload = {"jsonrpc": "2.0", "id": msg_id, "method": method}
        if params is not None:
            payload["params"] = params
        reply = self._post(payload, timeout=timeout, want_id=msg_id)
        if reply is None:
            raise ProtocolError(f"服务端没有返回 {method} 的响应（可能提前关闭了连接）")
        if "error" in reply and reply["error"]:
            err = reply["error"] if isinstance(reply["error"], dict) else {"message": str(reply["error"])}
            raise ServerError(f"{method} 失败：{err.get('message') or err}（code={err.get('code')}）",
                              detail=json.dumps(err, ensure_ascii=False)[:400])
        result = reply.get("result")
        return result if isinstance(result, dict) else {}

    def notify(self, method: str, params: Optional[dict] = None) -> None:
        payload = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        try:
            self._post(payload, want_id=_MISSING)
        except ClubError:
            # 通知失败不该让整个会话崩溃（部分实现会直接 202 空响应）
            pass

    # —— 会话层 ——

    def initialize(self) -> dict:
        result = self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": CLIENT_NAME, "version": CLIENT_VERSION},
        })
        self.protocol_version = str(result.get("protocolVersion") or PROTOCOL_VERSION)
        self.server_info = result.get("serverInfo") or {}
        self.capabilities = result.get("capabilities") or {}
        self._initialized = True
        self.notify("notifications/initialized")
        return result

    def ensure(self) -> "McpClient":
        if not self._initialized:
            self.initialize()
        return self

    def list_tools(self, *, refresh: bool = False) -> list:
        if self._tools is None or refresh:
            self.ensure()
            result = self.request("tools/list", {})
            tools = result.get("tools") or []
            self._tools = [t for t in tools if isinstance(t, dict)]
        return self._tools

    def call_tool(self, name: str, arguments: Optional[dict] = None,
                  *, timeout: float = CALL_TIMEOUT) -> dict:
        self.ensure()
        result = self.request("tools/call", {"name": name, "arguments": arguments or {}},
                             timeout=timeout)
        if result.get("isError"):
            raise ToolError(f"工具 {name} 返回错误：{result_text(result)[:400]}")
        return result

    def close(self) -> None:
        """尽量礼貌地结束会话（DELETE 失败无所谓，服务端会超时回收）。"""
        if not self.session_id:
            return
        req = urllib.request.Request(self.base_url, method="DELETE", headers=self._headers())
        try:
            urllib.request.urlopen(req, timeout=5).close()
        except Exception:  # noqa: BLE001
            pass

    # —— 桥接用：原样转发一条客户端消息 ——

    def exchange(self, message: dict,
                 on_message: Optional[Callable[[dict], None]] = None) -> Optional[dict]:
        """把 MCP 客户端发来的一条消息原样转发，返回服务端的完整 JSON-RPC 响应。"""
        if "id" not in message:  # 通知
            self._post(message, want_id=_MISSING, on_message=on_message)
            return None
        timeout = max(self.timeout, CALL_TIMEOUT) if message.get("method") == "tools/call" else self.timeout
        reply = self._post(message, want_id=message.get("id"), on_message=on_message, timeout=timeout)
        if message.get("method") == "initialize" and reply and isinstance(reply.get("result"), dict):
            self._initialized = True
            self.protocol_version = str(reply["result"].get("protocolVersion") or PROTOCOL_VERSION)
        return reply


# ─────────────────────────── 结果整形 ───────────────────────────

def result_text(result: dict) -> str:
    """把 tools/call 的 content 数组拼成人类可读文本。"""
    if not isinstance(result, dict):
        return str(result)
    parts: list[str] = []
    for item in result.get("content") or []:
        if not isinstance(item, dict):
            parts.append(str(item))
            continue
        kind = item.get("type")
        if kind == "text":
            parts.append(str(item.get("text") or ""))
        elif kind == "resource":
            res = item.get("resource") or {}
            uri = res.get("uri") or ""
            text = res.get("text")
            parts.append(text if text else f"[资源] {uri}")
        elif kind == "image":
            parts.append(f"[图片] {item.get('mimeType') or ''}".strip())
        else:
            parts.append(json.dumps(item, ensure_ascii=False)[:800])
    if not parts and result.get("structuredContent") is not None:
        parts.append(json.dumps(result["structuredContent"], ensure_ascii=False, indent=2))
    return "\n".join(p for p in parts if p is not None).strip()


def token_expiry(token: str) -> Optional[datetime]:
    """从 JWT 形态的令牌里读出 `exp`（**只解码，不验签**）。读不出返回 None。

    金蝶云社区的个人令牌是 JWT（服务端会用 "decode the Jwt" 报错），
    所以本地能先看一眼到期时间，省得用户对着 401 猜。
    """
    parts = (token or "").split(".")
    if len(parts) != 3:
        return None
    try:
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, binascii.Error):
        return None
    if not isinstance(data, dict):
        return None
    exp = data.get("exp")
    if isinstance(exp, (int, float)):
        ticks = float(exp)
        if ticks > 1e12:  # 毫秒
            ticks /= 1000.0
        try:
            return datetime.fromtimestamp(ticks)
        except (OverflowError, OSError, ValueError):
            return None
    return None


def expiry_text(token: str) -> str:
    """给人看的一句话（不含任何令牌内容）。"""
    when = token_expiry(token)
    if when is None:
        return "有效期未知（非 JWT 形态）"
    left = when - datetime.now()
    if left.total_seconds() <= 0:
        return f"已于 {when:%Y-%m-%d %H:%M} 过期"
    days = left.days
    return f"有效期至 {when:%Y-%m-%d %H:%M}（剩 {days} 天）"


def describe_tool(tool: dict) -> str:
    """一行描述：名字 + 说明首句 + 必填参数。"""
    name = tool.get("name") or "?"
    desc = (tool.get("description") or "").strip().replace("\n", " ")
    schema = tool.get("inputSchema") or {}
    required = schema.get("required") or []
    head = desc.split("。")[0][:80] if desc else ""
    tail = f"（必填：{', '.join(required)}）" if required else ""
    return f"{name} — {head}{tail}" if head else f"{name}{tail}"


if __name__ == "__main__":
    print("自带自检请用：python club_cli.py --verify", file=sys.stderr)
    try:
        c = McpClient()
        c.initialize()
        print("服务端:", c.server_info)
        for t in c.list_tools():
            print(" -", describe_tool(t))
    except ClubError as e:
        print(f"[{e.kind}] {e}", file=sys.stderr)
        sys.exit(2)
