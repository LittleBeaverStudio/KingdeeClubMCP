# 各客户端接入金蝶云社区 MCP

本技能生成的配置**只有启动命令，没有令牌**（令牌在 DPAPI 密文里）。所以每个客户端要做的事就三件：

1. 把 `kingdee-club` 这一段加进配置文件（或让 `python club_cli.py --install-mcp --client <名字>` 帮你写）；
2. 在客户端里**信任 / 启用**这个 MCP 服务；
3. 重启客户端（多数客户端只在启动时读一次配置）。

先生成片段：

```bash
python club_cli.py --mcp-config --client <名字>
```

`<名字>` 可选：`workbuddy` `cursor` `trae` `kiro` `windsurf` `claude` `vscode` `lingma`。

---

## 配置文件位置

| 客户端 | 配置文件 | 顶层键 | 界面入口 |
|---|---|---|---|
| **WorkBuddy** | `C:\Users\<你>\.workbuddy\mcp.json` | `mcpServers` | 连接器管理页 → 自定义连接器 → 点「信任」 |
| **Cursor** | `C:\Users\<你>\.cursor\mcp.json` | `mcpServers` | Settings → MCP → Add new global MCP server |
| **Trae（字节）** | `C:\Users\<你>\.trae\mcp.json` | `mcpServers` | Settings → MCP → Add MCP Server |
| **通义灵码（阿里）** | 面板内维护 | `mcpServers` | MCP 管理面板 → 添加 MCP Server |
| **Kiro（AWS）** | `C:\Users\<你>\.kiro\settings\mcp.json`（或项目内 `.kiro/settings/mcp.json`） | `mcpServers` | MCP 配置面板 |
| **Windsurf** | `C:\Users\<你>\.codeium\windsurf\mcp_config.json` | `mcpServers` | Settings → MCP |
| **Claude Desktop** | `%APPDATA%\Claude\claude_desktop_config.json` | `mcpServers` | Settings → Developer → Edit Config |
| **VS Code (Copilot)** | 工作区 `.vscode\mcp.json` | `servers` | 命令面板 → MCP: Add Server |

> 路径里 `<你>` 是你的 Windows 用户名。`~`、`$HOME` 这类写法有些客户端不认，**一律写绝对路径**。

---

## 标准片段（stdio，推荐）

```json
{
  "mcpServers": {
    "kingdee-club": {
      "command": "C:\\Users\\<你>\\AppData\\Local\\Programs\\Python\\Python311\\python.exe",
      "args": ["C:\\Users\\<你>\\.workbuddy\\skills\\kingdee-club\\club_bridge.py"]
    }
  }
}
```

- `command` 写**能用标准库跑起来的 Python 绝对路径**。`--mcp-config` 会自动填成**当前解释器**的路径；
  如果你换过 Python（升级、重装、换 venv），这个路径会失效 → 重跑一次 `--install-mcp` 即可。
- `args` 指向 `club_bridge.py` 的**绝对路径**。
- 不需要 `env`、不需要 `headers`、**不需要 `type`**（stdio 是默认传输）。

VS Code 额外要 `"type": "stdio"`，且顶层键是 `servers` —— `--client vscode` 已经处理好。

---

## 分客户端步骤

### WorkBuddy

```bash
python club_cli.py --install-mcp
```

然后打开**连接器管理页** → 找到 `kingdee-club` → 点「**信任**」（不点这一下不会加载）→ 重启 WorkBuddy。
新会话里问一句「用金蝶云社区查一下 XXX 报错」，能看到工具被调用就通了。

### Cursor

```bash
python club_cli.py --install-mcp --client cursor
```

Settings → MCP，列表里 `kingdee-club` 变绿即已连接；若显示红点，点开看 stderr（多半是 Python 路径错）。

### Claude Desktop

```bash
python club_cli.py --install-mcp --client claude
```

完全退出 Claude（托盘里也要退），再启动。Claude Desktop 对 stdout 很敏感，
本技能的桥已经把非协议输出全部赶到 stderr，正常不会出现 "Unexpected token" 之类的报错。

### Trae / 通义灵码 / Kiro / Windsurf

```bash
python club_cli.py --install-mcp --client trae       # 或 lingma / kiro / windsurf
```

如果这些客户端只提供「手动添加」表单，选 **stdio** 类型，命令与参数照抄 `--mcp-config` 的输出即可。

### VS Code (Copilot)

```bash
python club_cli.py --install-mcp --client vscode     # 写到当前目录 .vscode/mcp.json
```

Copilot Chat 里切到 Agent 模式，工具列表应出现 `kingdee-club` 下的工具。

---

## 备用写法：官方 HTTP 直连（**会把令牌写成明文**）

如果你确实不想用桥（比如客户端不支持 stdio），可以按官方文档直连：

```json
{
  "mcpServers": {
    "kingdee-club": {
      "type": "http",
      "url": "https://vip.kingdee.com/api/mcp",
      "headers": { "Authorization": "Bearer <你的个人令牌>" }
    }
  }
}
```

代价很直接：**令牌明文躺在 json 里**。`python club_cli.py --check` 会给你一条「⚠️ 含明文令牌」的告警。
真要走这条路，建议给令牌设最短有效期，泄露后立刻去社区重置。
