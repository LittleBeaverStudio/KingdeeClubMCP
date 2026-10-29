# -*- coding: utf-8 -*-
"""金蝶云社区 MCP 命令行：查状态、连自检、列工具、调工具、生成/写入 MCP 配置。

用法
────
    python club_cli.py --check                 # 只看本地状态（不联网）
    python club_cli.py --verify                # 真实连接自检（initialize + tools/list）
    python club_cli.py --tools                 # 列出服务端提供的工具
    python club_cli.py --call <工具名> --args '{"query":"..."}'   # 直接调一个工具
    python club_cli.py --mcp-config            # 生成 MCP 配置片段（默认 WorkBuddy）
    python club_cli.py --install-mcp           # 合并写入 ~/.workbuddy/mcp.json（自动备份）
    python club_cli.py --doctor                # 六步体检

退出码（agent 按码判断，不要猜输出文字）
────────────────────────────────────────
    0  成功                  2  缺少令牌（未配置）
    3  令牌被拒（401/403）    4  网络/代理不可达
    5  服务端错误 / 协议错误  6  工具执行返回错误
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import club_mcp  # noqa: E402
import clubstore  # noqa: E402

EXIT_OK = 0
EXIT_TOKEN_MISSING = 2
EXIT_TOKEN_REJECTED = 3
EXIT_TRANSPORT = 4
EXIT_SERVER = 5
EXIT_TOOL = 6

EXIT_BY_KIND = {
    "token-missing": EXIT_TOKEN_MISSING,
    "token-rejected": EXIT_TOKEN_REJECTED,
    "transport": EXIT_TRANSPORT,
    "server": EXIT_SERVER,
    "protocol": EXIT_SERVER,
    "tool": EXIT_TOOL,
}

SERVER_KEY = "kingdee-club"

CLIENTS = {
    "workbuddy": {
        "label": "WorkBuddy",
        "path": Path.home() / ".workbuddy" / "mcp.json",
        "key": "mcpServers",
        "extra": {},
    },
    "cursor": {
        "label": "Cursor",
        "path": Path.home() / ".cursor" / "mcp.json",
        "key": "mcpServers",
        "extra": {},
    },
    "trae": {
        "label": "Trae",
        "path": Path.home() / ".trae" / "mcp.json",
        "key": "mcpServers",
        "extra": {},
    },
    "kiro": {
        "label": "Kiro",
        "path": Path.home() / ".kiro" / "settings" / "mcp.json",
        "key": "mcpServers",
        "extra": {},
    },
    "windsurf": {
        "label": "Windsurf",
        "path": Path.home() / ".codeium" / "windsurf" / "mcp_config.json",
        "key": "mcpServers",
        "extra": {},
    },
    "claude": {
        "label": "Claude Desktop",
        "path": (Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
                 / "Claude" / "claude_desktop_config.json"),
        "key": "mcpServers",
        "extra": {},
    },
    "vscode": {
        "label": "VS Code (Copilot)",
        "path": Path(".vscode") / "mcp.json",  # 相对当前工作区
        "key": "servers",
        "extra": {"type": "stdio"},
    },
    "lingma": {
        "label": "通义灵码",
        "path": None,
        "key": "mcpServers",
        "extra": {},
    },
}


# ─────────────────────────── 小工具 ───────────────────────────

def _entry(extra: dict | None = None) -> dict:
    """生成一条 stdio MCP 配置：命令 + 桥脚本，**不含任何令牌**。"""
    entry = {
        "command": sys.executable,
        "args": [str(HERE / "club_bridge.py")],
    }
    entry.update(extra or {})
    return entry


def _config_doc(client: str) -> dict:
    meta = CLIENTS[client]
    return {meta["key"]: {SERVER_KEY: _entry(meta["extra"])}}


def _print_json(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("顶层不是一个 JSON 对象")
    return data


def _scan_plaintext_token(text: str) -> bool:
    """粗判配置文件里有没有明文 Bearer 令牌（用于安全提醒，不做抢救）。"""
    return re.search(r"Bearer\s+[A-Za-z0-9._\-]{12,}", text) is not None


def _find_configured() -> list[tuple[str, Path, bool]]:
    """返回已配置 kingdee-club 的客户端列表：(key, path, 是否含明文令牌)。"""
    found = []
    for key, meta in CLIENTS.items():
        path: Path | None = meta["path"]
        if not path or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if SERVER_KEY not in text:
            continue
        found.append((key, path, _scan_plaintext_token(text)))
    return found


# ─────────────────────────── 各子命令 ───────────────────────────

def cmd_check(base_url: str | None) -> int:
    print("服务地址  :", club_mcp.resolve_base_url(base_url))
    try:
        token, source = club_mcp.resolve_token()
        print("令牌      :", f"{source}｜{clubstore.mask(token)}")
        print("有效期    :", club_mcp.expiry_text(token))
    except club_mcp.TokenMissing:
        print("令牌      : 未配置（运行 python setup_token.py）")
    conf = _find_configured()
    if conf:
        for key, path, plain in conf:
            flag = "⚠️ 含明文令牌" if plain else "✅ 仅启动桥脚本，无令牌"
            print(f"MCP 配置  : {CLIENTS[key]['label']} → {path}（{flag}）")
    else:
        print("MCP 配置  : 未找到 kingdee-club 条目（python club_cli.py --mcp-config 查看片段）")
    print("提示      : 本命令不联网；真实连通性用 --verify")
    return EXIT_OK


def cmd_verify(client: club_mcp.McpClient) -> int:
    print("服务地址  :", client.base_url)
    print("令牌      :", f"{client.token_source}｜{clubstore.mask(client.token)}")
    print("有效期    :", club_mcp.expiry_text(client.token))
    info = client.initialize()
    server = client.server_info or {}
    print("协议版本  :", client.protocol_version, "（服务端返回", info.get("protocolVersion"), "）")
    name = server.get("name") or "（未提供）"
    version = server.get("version") or ""
    print("服务端    :", f"{name} {version}".strip())
    if client.session_id:
        print("会话 ID   :", clubstore.mask(client.session_id))
    tools = client.list_tools()
    print(f"工具数量  : {len(tools)}")
    for tool in tools:
        print("  ·", club_mcp.describe_tool(tool))
    client.close()
    print("\n✅ 连接正常。")
    return EXIT_OK


def cmd_tools(client: club_mcp.McpClient, as_json: bool) -> int:
    tools = client.list_tools()
    if as_json:
        _print_json(tools)
    else:
        print(f"共 {len(tools)} 个工具：\n")
        for tool in tools:
            print("·", tool.get("name"))
            desc = (tool.get("description") or "").strip()
            if desc:
                print("  " + desc.replace("\n", "\n  ")[:600])
            schema = tool.get("inputSchema") or {}
            props = schema.get("properties") or {}
            required = set(schema.get("required") or [])
            if props:
                print("  参数：")
                for pname, spec in props.items():
                    spec = spec if isinstance(spec, dict) else {}
                    mark = "（必填）" if pname in required else ""
                    ptype = spec.get("type") or ""
                    pdesc = (spec.get("description") or "").strip().replace("\n", " ")
                    print(f"    - {pname} {ptype}{mark} {pdesc}"[:200])
            print()
    client.close()
    return EXIT_OK


def cmd_call(client: club_mcp.McpClient, name: str, raw_args: str, as_json: bool) -> int:
    try:
        arguments = json.loads(raw_args) if raw_args.strip() else {}
    except ValueError as exc:
        print(f"[参数错误] --args 不是合法 JSON：{exc}", file=sys.stderr)
        return EXIT_TOOL
    if not isinstance(arguments, dict):
        print("[参数错误] --args 必须是一个 JSON 对象", file=sys.stderr)
        return EXIT_TOOL
    result = client.call_tool(name, arguments)
    client.close()
    if as_json:
        _print_json(result)
    else:
        text = club_mcp.result_text(result)
        print(text or "（工具没有返回文本内容）")
    return EXIT_OK


def cmd_mcp_config(client_key: str, as_json_only: bool) -> int:
    meta = CLIENTS[client_key]
    doc = _config_doc(client_key)
    if as_json_only:
        _print_json(doc)
        return EXIT_OK
    print(f"# {meta['label']}（{client_key}）")
    if meta["path"]:
        print(f"# 配置文件：{meta['path']}")
    print("# 说明：这里只有启动命令，没有令牌 —— 令牌在 DPAPI 密文里，运行期才读。")
    _print_json(doc)
    print("\n# 合并方式：把上面 \"kingdee-club\" 这一段加进配置文件的"
          f" \"{meta['key']}\" 里，或直接运行：python club_cli.py --install-mcp --client {client_key}")
    return EXIT_OK


def cmd_install_mcp(client_key: str, dry_run: bool) -> int:
    meta = CLIENTS[client_key]
    path: Path | None = meta["path"]
    if path is None:
        print(f"[!] {meta['label']} 没有固定的配置文件路径，请在它的 MCP 面板里手动添加：", file=sys.stderr)
        _print_json(_config_doc(client_key))
        return EXIT_SERVER

    if path.is_file():
        try:
            data = _load_json(path)
        except (ValueError, OSError) as exc:
            print(f"[!] 现有配置无法解析为 JSON，为避免破坏它，本次不写入：{path}\n    {exc}",
                  file=sys.stderr)
            return EXIT_SERVER
    else:
        data = {}

    container = data.setdefault(meta["key"], {})
    if not isinstance(container, dict):
        print(f"[!] 现有配置里的 \"{meta['key']}\" 不是对象，本次不写入。", file=sys.stderr)
        return EXIT_SERVER
    before = json.dumps(container.get(SERVER_KEY), ensure_ascii=False, sort_keys=True)
    container[SERVER_KEY] = _entry(meta["extra"])
    after = json.dumps(container[SERVER_KEY], ensure_ascii=False, sort_keys=True)

    if before == after:
        print(f"✅ 已经是目标配置，无需修改：{path}")
        return EXIT_OK

    rendered = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if dry_run:
        print(f"# 将要写入 {path}：\n")
        print(rendered)
        return EXIT_OK

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            backup = path.with_name(path.name + ".bak-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
            shutil.copy2(path, backup)
            print(f"已备份原配置 → {backup}")
        path.write_text(rendered, encoding="utf-8")
    except OSError as exc:
        print(f"[!] 写入失败：{exc}", file=sys.stderr)
        return EXIT_SERVER

    print(f"✅ 已写入 {path}")
    print(f"   {SERVER_KEY} = {sys.executable} {HERE / 'club_bridge.py'}")
    print("   下一步：在客户端里【信任/启用】这个 MCP 服务（WorkBuddy 在连接器管理页点「信任」），"
          "然后重启客户端。")
    return EXIT_OK


def cmd_doctor(base_url: str | None) -> int:
    rc = EXIT_OK
    print("== 1. 运行环境 ==")
    print("   Python :", sys.version.split()[0], platform.architecture()[0])
    print("   平台   :", platform.platform())
    print("   DPAPI  :", "可用" if clubstore.available() else "不可用（非 Windows，只能用环境变量）")
    print("   技能目录:", HERE)

    print("\n== 2. 令牌 ==")
    token = ""
    source = ""
    try:
        token, source = club_mcp.resolve_token()
        print(f"   状态   : 已配置 —— {source}｜{clubstore.mask(token)}")
        print("   有效期 :", club_mcp.expiry_text(token))
        data = clubstore.load() or {}
        if data.get("saved_at"):
            print("   保存于 :", data.get("saved_at"))
    except club_mcp.TokenMissing as exc:
        print("   状态   : ❌ 未配置")
        print("   处理   :", exc)
        rc = EXIT_TOKEN_MISSING

    url = club_mcp.resolve_base_url(base_url)
    print("\n== 3. 端点可达性（不带令牌） ==")
    print("   地址   :", url)
    probe = club_mcp.McpClient(base_url=url, timeout=20, need_token=False)
    try:
        reply = probe._post({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": club_mcp.PROTOCOL_VERSION, "capabilities": {},
            "clientInfo": {"name": club_mcp.CLIENT_NAME, "version": club_mcp.CLIENT_VERSION}}},
            want_id=1)
        print("   结果   : ✅ 无令牌也返回了响应（该服务可能不要求鉴权）")
    except club_mcp.TokenRejected:
        print("   结果   : ✅ 端点存活且要求鉴权（401/403 属预期）")
    except club_mcp.ClubError as exc:
        print(f"   结果   : ❌ {exc.kind} —— {exc}")
        if exc.kind in ("transport",):
            rc = EXIT_TRANSPORT
        elif rc == EXIT_OK:
            rc = EXIT_SERVER

    if token:
        print("\n== 4. 带令牌握手 ==")
        client = club_mcp.McpClient(token=token, base_url=url, timeout=45, need_token=False)
        try:
            client.initialize()
            tools = client.list_tools()
            print(f"   结果   : ✅ 协议 {client.protocol_version}，工具 {len(tools)} 个")
            client.close()
        except club_mcp.ClubError as exc:
            print(f"   结果   : ❌ {exc.kind} —— {exc}")
            rc = EXIT_BY_KIND.get(exc.kind, EXIT_SERVER)
    else:
        print("\n== 4. 带令牌握手 ==")
        print("   跳过   : 没有令牌")

    print("\n== 5. MCP 配置 ==")
    conf = _find_configured()
    if not conf:
        print("   ❌ 没找到 kingdee-club 条目")
        print("   处理   : python club_cli.py --mcp-config 生成片段，或 --install-mcp 直接写入")
    for key, path, plain in conf:
        print(f"   {CLIENTS[key]['label']}: {path}")
        if plain:
            print("   ⚠️ 该配置里有明文 Bearer 令牌 —— 建议改成本技能的 stdio 桥，别把令牌摊在 json 里")
    print("   桥脚本 :", HERE / "club_bridge.py")

    print("\n== 6. 结论 ==")
    print({0: "✅ 一切正常", 2: "⚠️ 还差令牌：python setup_token.py",
           3: "❌ 令牌被拒：换一个新令牌", 4: "❌ 网络/代理问题",
           5: "❌ 服务端或协议问题"}.get(rc, "❌ 有问题"))
    return rc


# ─────────────────────────── 入口 ───────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="金蝶云社区 MCP 命令行（令牌走 DPAPI 密文，不落明文）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="退出码：0 成功｜2 缺令牌｜3 令牌被拒｜4 网络｜5 服务端｜6 工具错误")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="只看本地状态，不联网")
    group.add_argument("--verify", action="store_true", help="连接自检（initialize + tools/list）")
    group.add_argument("--tools", action="store_true", help="列出服务端工具")
    group.add_argument("--call", metavar="TOOL", help="调用一个工具")
    group.add_argument("--mcp-config", action="store_true", help="生成 MCP 配置片段")
    group.add_argument("--install-mcp", action="store_true", help="合并写入 MCP 配置文件")
    group.add_argument("--doctor", action="store_true", help="六步体检")

    parser.add_argument("--args", default="{}", help="--call 的参数（JSON 对象）")
    parser.add_argument("--json", action="store_true", help="--tools / --call 输出原始 JSON")
    parser.add_argument("--client", default="workbuddy", choices=sorted(CLIENTS),
                        help="--mcp-config / --install-mcp 的目标客户端")
    parser.add_argument("--base-url", default=None, help="覆盖服务地址")
    parser.add_argument("--timeout", type=float, default=None, help="单次请求超时（秒）")
    parser.add_argument("--dry-run", action="store_true", help="--install-mcp 只打印不写文件")
    args = parser.parse_args()

    try:
        if args.check:
            return cmd_check(args.base_url)
        if args.doctor:
            return cmd_doctor(args.base_url)
        if args.mcp_config:
            return cmd_mcp_config(args.client, args.json)
        if args.install_mcp:
            return cmd_install_mcp(args.client, args.dry_run)

        client = club_mcp.McpClient(base_url=args.base_url, timeout=args.timeout or club_mcp.DEFAULT_TIMEOUT)
        if args.verify:
            return cmd_verify(client)
        if args.tools:
            return cmd_tools(client, args.json)
        if args.call:
            return cmd_call(client, args.call, args.args, args.json)
        parser.print_help()
        return EXIT_OK
    except club_mcp.ClubError as exc:
        print(f"[{exc.kind}] {exc}", file=sys.stderr)
        if exc.detail:
            print(f"  服务端原文：{exc.detail}", file=sys.stderr)
        return EXIT_BY_KIND.get(exc.kind, EXIT_SERVER)
    except KeyboardInterrupt:
        print("\n已中断", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
