# -*- coding: utf-8 -*-
"""MCP stdio ↔ 金蝶云社区 HTTP 桥。

存在的理由
──────────
金蝶云社区提供的是 **HTTP 型** MCP（`https://vip.kingdee.com/api/mcp`），按官方写法要把
`Authorization: Bearer <个人令牌>` 明文写进客户端的 `mcp.json`。这等于把令牌摊在磁盘上：
一旦这个 json 被截图、同步到网盘、进 git、发给同事排障，令牌就外泄了。

本桥把「令牌」和「配置文件」彻底分开：

    mcp.json 里只有 → python club_bridge.py     （不含任何机密）
    令牌在           → DPAPI 密文 club_token.bin （绑当前 Windows 用户）
    运行期           → 只在进程内存里拼 Authorization 头

对 MCP 客户端来说，它就是一个普通的 stdio MCP 服务（`initialize` / `tools/list` /
`tools/call` 全都照常）；对金蝶云社区来说，它就是一次普通的 HTTP MCP 会话。

实现要点
────────
· **stdout 是协议通道**：启动时先把真正的 stdout 句柄 dup 出来，再把 `sys.stdout`
  重定向到 stderr，任何库的误打印都不会污染 JSON-RPC 帧；
· 一行一条 JSON（MCP stdio 传输规范），UTF-8，不换行内嵌；
· 每个请求一个线程，避免一个慢查询（`tools/call` 可能几十秒）卡住整个会话；
· 令牌**不接受命令行参数**（会进进程列表和 shell 历史），只走 DPAPI 或环境变量。

用法（写进 mcp.json）：
    {"command": "<python 绝对路径>", "args": ["<技能目录>/club_bridge.py"]}
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import club_mcp  # noqa: E402

LOG_PREFIX = "[kingdee-club]"


def log(message: str) -> None:
    print(f"{LOG_PREFIX} {message}", file=sys.stderr, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="金蝶云社区 MCP stdio 桥（令牌走 DPAPI 密文）")
    parser.add_argument("--base-url", default=None, help="覆盖服务地址（默认取 DPAPI/env/内置值）")
    parser.add_argument("--timeout", type=float, default=None,
                        help=f"单次 HTTP 超时秒数（默认 {club_mcp.DEFAULT_TIMEOUT:g}）")
    args = parser.parse_args()

    # ① 先抢下真正的 stdout，之后任何 print 都去 stderr
    try:
        protocol_out = os.fdopen(os.dup(sys.stdout.fileno()), "wb", 0)
    except (OSError, ValueError):
        protocol_out = sys.stdout.buffer
    sys.stdout = sys.stderr

    write_lock = threading.Lock()

    def write_message(message: dict) -> None:
        data = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        with write_lock:
            try:
                protocol_out.write(data)
                protocol_out.flush()
            except (BrokenPipeError, OSError):
                pass  # 客户端已经退出

    def error_reply(msg_id, message: str, code: int = -32603) -> None:
        write_message({"jsonrpc": "2.0", "id": msg_id,
                       "error": {"code": code, "message": message}})

    try:
        client = club_mcp.McpClient(base_url=args.base_url,
                                    timeout=args.timeout or club_mcp.DEFAULT_TIMEOUT,
                                    need_token=False)
    except club_mcp.ClubError as exc:  # 地址配置错误：启动即失败，说清楚
        log(f"启动失败：{exc}")
        return 2

    # 令牌延迟到第一次真正需要时解析：这样"还没配令牌"能作为一条 MCP 错误返回给客户端，
    # 而不是让客户端只看到"服务启动失败"。**不缓存失败结果**——用户补配令牌后无需重启客户端。
    token_state = {"ready": False}

    def ensure_token() -> None:
        if token_state["ready"]:
            return
        client.token, client.token_source = club_mcp.resolve_token()
        token_state["ready"] = True

    def handle(raw: bytes) -> None:
        line = raw.strip()
        if not line:
            return
        try:
            message = json.loads(line.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            log(f"忽略无法解析的输入（{len(line)} 字节）")
            return
        if not isinstance(message, dict):
            return
        msg_id = message.get("id", _NO_ID)
        try:
            ensure_token()
            reply = client.exchange(message, on_message=write_message)
        except club_mcp.ClubError as exc:
            log(f"{message.get('method')} 失败：{exc}")
            if isinstance(exc, club_mcp.TokenRejected):
                # 令牌换了：下次请求重新读一次密文，用户无需重启客户端
                token_state["ready"] = False
            if msg_id is not _NO_ID:
                error_reply(msg_id, str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - 桥不能死，任何异常都要回一条错误
            log(f"未预期错误：{type(exc).__name__}: {exc}")
            if msg_id is not _NO_ID:
                error_reply(msg_id, f"桥内部错误：{type(exc).__name__}: {exc}")
            return
        if reply is not None:
            write_message(reply)

    log(f"已启动，目标 {client.base_url}")
    workers: list[threading.Thread] = []
    stdin = sys.stdin.buffer
    try:
        for raw in stdin:
            worker = threading.Thread(target=handle, args=(raw,), daemon=True)
            worker.start()
            workers.append(worker)
            workers = [w for w in workers if w.is_alive()]
    except KeyboardInterrupt:
        pass
    finally:
        deadline = time.time() + 3.0
        for worker in workers:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            worker.join(remaining)
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass
        log("已退出")
    return 0


class _NoId:
    def __repr__(self) -> str:  # 仅用于区分"没有 id"和 id=None
        return "<no-id>"


_NO_ID = _NoId()

if __name__ == "__main__":
    sys.exit(main())
