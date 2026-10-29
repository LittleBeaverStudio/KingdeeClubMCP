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
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import club_mcp  # noqa: E402
import clubstore  # noqa: E402

# stdout 常被 agent 当成管道读（不是 tty），默认是块缓冲 —— 进度会憋在缓冲区里，
# agent 轮询时看不到「窗口已打开」这类提示。改成行缓冲，逐行立刻可见。
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except (AttributeError, ValueError):  # 老 Python / 特殊 stdout
    pass

EXIT_OK = 0
EXIT_TOKEN_MISSING = 2
EXIT_TOKEN_REJECTED = 3
EXIT_TRANSPORT = 4
EXIT_SERVER = 5
EXIT_TOOL = 6
EXIT_MANUAL = 7

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


def run_token_wizard() -> int:
    """拉起令牌录入窗口（子进程），返回它的退出码。

    为什么用子进程而不是直接调 `setup_token._gui()`：
    `setup_token.py` 自带「当前解释器没有 tkinter 就换一个 Python 开窗」的逻辑，
    走子进程才能复用它；子进程会把自己的 SETUP_RESULT 摘要打进同一份 stdout。
    """
    script = HERE / "setup_token.py"
    if not script.is_file():
        print(f"[!] 找不到令牌向导：{script}", file=sys.stderr)
        return EXIT_SERVER
    try:
        done = subprocess.run([sys.executable, str(script)])
    except OSError as exc:
        print(f"[!] 启动令牌窗口失败：{exc}", file=sys.stderr)
        return EXIT_SERVER
    return done.returncode


def cmd_setup(base_url: str | None, client_key: str, timeout: float | None,
              with_mcp: bool = False) -> int:
    """一条命令走完：录令牌 → 自检（→ 可选写 MCP 配置）。

    这是给 agent 用的入口：用户回一句「令牌准备好了」，agent 就跑这一条，
    不要让用户自己敲命令。最后打印 SETUP_RESULT 摘要，agent 按它判断。

    默认**不写 MCP 配置** —— 因为注册成 MCP 服务后，用户还得去「连接器管理页 → 右上角
    自定义连接器」确认一次（客户端对"要启动本地进程"的安全闸门），日常查社区用不到。
    日常查社区用本技能自带的 `--search` / `--call` 就够了，不需要那两步。
    用户明确要求"让工具原生出现在客户端里"时，才加 `--with-mcp`。
    """
    print("=" * 68)
    print("金蝶云社区 MCP · 一步接入")
    print("=" * 68)

    # 本次以 DPAPI 密文为准：环境变量里的旧令牌会让自检测错对象
    saved_env = {}
    for name in club_mcp.TOKEN_ENVS:
        if name in os.environ:
            saved_env[name] = os.environ.pop(name)

    try:
        # —— 第 1 步：令牌 ——
        print("\n[1/3] 令牌")
        try:
            token, source = club_mcp.resolve_token()
            print(f"      已配置（{source}｜{clubstore.mask(token)}），跳过录入窗口。")
            print("      要重新录入：python setup_token.py --delete 后再跑本命令。")
        except club_mcp.TokenMissing:
            print("      正在打开录入窗口 —— 请把令牌粘贴进去，点「测试连接」，再点「保存并关闭」。")
            code = run_token_wizard()
            if code == 10:
                print("      用户取消了，**没有做任何改动**（也没写配置）。")
                print("SETUP_RESULT code=10 stage=token saved=0 verified=0 installed=0")
                return EXIT_TOKEN_MISSING
            if code != 0:
                print(f"      令牌录入未完成（退出码 {code}），已中止，没有写任何配置。")
                print(f"SETUP_RESULT code={code} stage=token saved=0 verified=0 installed=0")
                return code if code in (2, 3, 4) else EXIT_SERVER

        # —— 第 2 步：自检 ——
        print("\n[2/3] 连接自检")
        client = club_mcp.McpClient(base_url=base_url, timeout=timeout or club_mcp.DEFAULT_TIMEOUT)
        try:
            cmd_verify(client)
        except club_mcp.ClubError as exc:
            print(f"      ❌ {exc}")
            print(f"SETUP_RESULT code={EXIT_BY_KIND.get(exc.kind, EXIT_SERVER)} "
                  f"stage=verify saved=1 verified=0 installed=0")
            return EXIT_BY_KIND.get(exc.kind, EXIT_SERVER)

        # —— 第 3 步（可选）：注册成 MCP 服务 ——
        if with_mcp:
            print("\n[3/3] 写入 MCP 配置")
            rc = cmd_install_mcp(client_key, dry_run=False)
            if rc != 0:
                print(f"SETUP_RESULT code={rc} stage=install saved=1 verified=1 installed=0")
                return rc
            print("\n" + "=" * 68)
            print("✅ 令牌已加密保存 · 连接自检通过 · MCP 配置已写入")
            print("=" * 68)
            print(f"配置文件：{CLIENTS[client_key]['path']}")
            print("最后一步（只有人能做）：连接器管理页右上角「自定义连接器」→ 找到 kingdee-club → 确认启用。")
            print("新版客户端保存即生效，一般不用重启；对话里展开「正在连接 MCP 服务」可看是否连上。")
            print("SETUP_RESULT code=0 stage=ready saved=1 verified=1 installed=1 next=trust_and_restart")
            return EXIT_OK

        print("\n" + "=" * 68)
        print("✅ 令牌已加密保存 · 连接自检通过")
        print("=" * 68)
        print("已经可以用了：以后直接问「金蝶 XX 报错怎么办」，我会用这个技能去社区检索。")
        print("（想让它以「工具」形式出现在客户端里，再跑一次 python club_cli.py --setup --with-mcp，")
        print("  但那需要你去连接器管理页右上角「自定义连接器」确认一次 —— 不做也能用。）")
        print("SETUP_RESULT code=0 stage=ready saved=1 verified=1 installed=0 next=none")
        return EXIT_OK
    finally:
        os.environ.update(saved_env)


SEARCH_NAME_HINTS = ("search", "knowledge", "query", "article", "post", "community", "list")
QUERY_PARAM_HINTS = ("query", "keyword", "q", "question", "title", "text", "content", "search")
LIMIT_PARAM_HINTS = ("top_k", "topk", "limit", "size", "count", "num", "page_size")


def _pick_search_tool(tools: list) -> tuple[dict | None, str, str]:
    """从服务端工具里挑一个"搜索类"的，返回 (工具, 查询参数名, 条数参数名)。

    不写死工具名 —— 服务端升级可能改名，改名后这里会自动重新挑。
    """
    best, best_score = None, 0
    for tool in tools:
        name = (tool.get("name") or "").lower()
        props = ((tool.get("inputSchema") or {}).get("properties") or {})
        param = next((p for p in props if p.lower() in QUERY_PARAM_HINTS), None)
        limit = next((p for p in props if p.lower() in LIMIT_PARAM_HINTS), None)
        score = 0
        if any(h in name for h in SEARCH_NAME_HINTS):
            score += 3
        if param:
            score += 2
        if limit:
            score += 1
        if score > best_score:
            best, best_score = tool, score
            if param and any(h in name for h in ("search", "knowledge")):
                break
    if not best:
        return None, "", ""
    props = ((best.get("inputSchema") or {}).get("properties") or {})
    param = next((p for p in props if p.lower() in QUERY_PARAM_HINTS), "")
    limit = next((p for p in props if p.lower() in LIMIT_PARAM_HINTS), "")
    return best, param, limit


def cmd_search(client: club_mcp.McpClient, keyword: str, top_k: int | None,
              as_json: bool) -> int:
    """一句自然语言关键词 → 自动挑搜索工具 → 直接调。给"不想配 MCP"的用法。"""
    tools = client.list_tools()
    tool, param, limit_param = _pick_search_tool(tools)
    if tool is None:
        print("[!] 服务端没有可用工具，先看 `python club_cli.py --tools`", file=sys.stderr)
        client.close()
        return EXIT_TOOL
    if not param:
        print(f"[!] 工具 {tool.get('name')} 没有可识别的查询参数，请改用 --call 精确调用。"
              f"\n    可用工具：{', '.join(t.get('name', '?') for t in tools)}", file=sys.stderr)
        client.close()
        return EXIT_TOOL

    arguments = {param: keyword}
    if top_k and limit_param:
        arguments[limit_param] = int(top_k)
    result = client.call_tool(tool["name"], arguments)
    client.close()
    if as_json:
        _print_json(result)
    else:
        text = club_mcp.result_text(result)
        print(text or "（工具没有返回文本内容）")
    return EXIT_OK


def cmd_install_mcp(client_key: str, dry_run: bool) -> int:
    meta = CLIENTS[client_key]
    path: Path | None = meta["path"]
    if path is None:
        print(f"[!] {meta['label']} 没有固定的配置文件路径，请在它的 MCP 面板里手动添加：", file=sys.stderr)
        _print_json(_config_doc(client_key))
        return EXIT_MANUAL

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
    print("   下一步：连接器管理页右上角「自定义连接器」→ 找到 kingdee-club → 确认启用"
          "（也可直接编辑该配置文件；新版保存即生效，一般不用重启）。")
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
        epilog="退出码：0 成功｜2 缺令牌｜3 令牌被拒｜4 网络｜5 服务端｜6 工具错误｜7 需在客户端里手动配置")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="只看本地状态，不联网")
    group.add_argument("--verify", action="store_true", help="连接自检（initialize + tools/list）")
    group.add_argument("--tools", action="store_true", help="列出服务端工具")
    group.add_argument("--call", metavar="TOOL", help="调用一个工具")
    group.add_argument("--search", metavar="关键词", help="一句话检索社区（自动挑搜索工具）")
    group.add_argument("--mcp-config", action="store_true", help="生成 MCP 配置片段")
    group.add_argument("--install-mcp", action="store_true", help="合并写入 MCP 配置文件")
    group.add_argument("--setup", action="store_true",
                       help="一步接入：弹窗录令牌 → 自检 → 写入 MCP 配置（agent 用这个）")
    group.add_argument("--doctor", action="store_true", help="六步体检")

    parser.add_argument("--args", default="{}", help="--call 的参数（JSON 对象）")
    parser.add_argument("--top-k", type=int, default=None, help="--search 的返回条数（服务端支持时）")
    parser.add_argument("--json", action="store_true", help="--tools / --call 输出原始 JSON")
    parser.add_argument("--client", default="workbuddy", choices=sorted(CLIENTS),
                        help="--mcp-config / --install-mcp 的目标客户端")
    parser.add_argument("--base-url", default=None, help="覆盖服务地址")
    parser.add_argument("--timeout", type=float, default=None, help="单次请求超时（秒）")
    parser.add_argument("--dry-run", action="store_true", help="--install-mcp 只打印不写文件")
    parser.add_argument("--with-mcp", action="store_true",
                        help="--setup 额外把 MCP 配置写进客户端（需在连接器页确认一次）")
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
        if args.setup:
            return cmd_setup(args.base_url, args.client, args.timeout, args.with_mcp)

        client = club_mcp.McpClient(base_url=args.base_url, timeout=args.timeout or club_mcp.DEFAULT_TIMEOUT)
        if args.verify:
            return cmd_verify(client)
        if args.tools:
            return cmd_tools(client, args.json)
        if args.call:
            return cmd_call(client, args.call, args.args, args.json)
        if args.search:
            return cmd_search(client, args.search, args.top_k, args.json)
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
