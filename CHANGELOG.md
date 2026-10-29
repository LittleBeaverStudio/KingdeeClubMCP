# 更新日志

版本号规则：`主.次.修订`，**每次发布只 +0.0.1**（0–9 顺进，满 9 才进位）。

## 1.0.1 — 2026-10-29

### 修复

- 令牌窗口的「测试连接」改为**后台线程 + 队列回传**：结果在主线程更新控件。
  Tk 不是线程安全的，之前从子线程调 `root.after` 在部分机器上会让窗口直接崩掉。
- 通义灵码这类**没有固定配置文件**的客户端，`--install-mcp` 现在返回退出码 **7**（需手动配置），
  不再复用「5 服务端错误」——那个码会让人误以为是网络或服务端问题。

### 文档

- 退出码表补充 `7`。

## 1.0.0 — 2026-10-29

首个公开版本。

### 新增

- **令牌加密录入**（`setup_token.py`）：弹窗粘贴 → 测试连接 → 保存。
  用 Windows DPAPI（`CryptProtectData`）加密写入 `~/.workbuddy/kingdee/club_token.bin`，
  绑当前 Windows 用户；**不落明文、不进对话、不写日志**，只显示尾 4 位。
  与「数据导出」的 `credentials.bin` 是两个文件、互不覆盖。
  当前解释器缺 tkinter 时自动找本机已装的另一个 Python 开窗，最后退到文字向导（不安装任何东西）。
- **MCP 客户端**（`club_mcp.py`）：Streamable HTTP + SSE 双分支解析、`Mcp-Session-Id` 会话维护、
  协议版本协商、`initialize` / `notifications/initialized` / `tools/list` / `tools/call`，
  **纯标准库**（`urllib` / `json` / `ssl` / `ctypes`），零第三方依赖。
- **stdio 桥**（`club_bridge.py`）：让 `mcp.json` 里**不出现令牌** —— 配置只写「哪个 Python 跑哪个脚本」，
  令牌运行期才从密文读进内存。stdout 独占给 JSON-RPC（启动时 dup 真 stdout，其余输出改道 stderr），
  每个请求独立线程，慢查询不会卡住整个会话。
- **命令行**（`club_cli.py`）：`--check` / `--verify` / `--tools` / `--call` / `--mcp-config` /
  `--install-mcp` / `--doctor`。写入客户端配置前自动备份 `*.bak-<时间戳>`，保留其它服务条目。
- **令牌有效期**：本地解析 JWT 的 `exp`（只解码不验签），`--check` / `--verify` / `--doctor`
  直接告诉你「剩多少天」，省得对着 401 猜。
- **8 种客户端**：WorkBuddy / Cursor / Trae / 通义灵码 / Kiro / Windsurf / Claude Desktop / VS Code，
  配置路径与入口见 `references/mcp-clients.md`。
- **六步体检**（`--doctor`）：环境 → 令牌 → 端点可达性（不带令牌探测 401）→ 带令牌握手 →
  MCP 配置（含「明文令牌」告警）→ 结论。
- **文档**：`SKILL.md`（agent 用，含硬规矩：不得索要令牌）、`README.md`（用户用）、
  `references/error-playbook.md`（按报错原文查原因）。

### 安全

- 不使用官方 HTTP 直连时所需的明文 `headers` 写法；`--check` 会检测并告警已有配置里的明文 `Bearer`。
- 401/403 **不自动重试**（避免把账号打到风控）；错误信息保留服务端原文，便于判断是令牌还是权限问题。
- 不检查更新、不上报遥测、不访问除 `vip.kingdee.com` 之外的服务。
