> **本项目采用「小河狸工作室非转售许可 1.0」**——
> 个人使用与**企业内部使用免费**（含内部办公、财务与会计处理、内部系统集成）；
> 对外销售、集成进收费产品或服务、托管 / SaaS / 代运营、以及**向第三方交付成果或提供服务，须事先取得书面授权**。
> 许可全文见 [LICENSE](./LICENSE)。商业授权：https://littlebeaver.top

[![License](https://img.shields.io/badge/License-%E5%B0%8F%E6%B2%B3%E7%8B%B8%E9%9D%9E%E8%BD%AC%E5%94%AE%E8%AE%B8%E5%8F%AF-blue.svg)](./LICENSE)
[![Python](https://img.shields.io/badge/Python-3.8%2B-3776AB.svg)](https://www.python.org/)
[![Deps](https://img.shields.io/badge/%E4%BE%9D%E8%B5%96-%E9%9B%B6%E7%AC%AC%E4%B8%89%E6%96%B9%E5%8C%85-brightgreen.svg)](#-为什么不用装依赖)

# 金蝶云社区问答 Skill

把**金蝶云社区（vip.kingdee.com）的官方 MCP** 接进你的 AI 客户端。
之后遇到金蝶的问题，不用再开浏览器翻论坛 —— 直接在对话里问，AI 去社区里找**原文**并给出处。

> 一句话：**AI 能查社区了，但你的令牌不会出现在任何配置文件里。**

---

## 它到底解决什么问题

用金蝶的人都有这个循环：报错弹窗 → 看不懂 → 百度/搜社区 → 翻十几页帖子 → 找到一条 2021 年的回答 →
还不知道适不适用于自己的版本。

社区其实有官方 MCP（AI 可以直接检索社区内容），但官方接法要求把**个人令牌明文写进
`mcp.json`**：

```json
"headers": { "Authorization": "Bearer eyJhbGciOi..." }
```

这个文件会被截图发群、被网盘同步、被误提交、被发同事排障。令牌 = 你身份的凭证，泄一次就得去重置。

**本技能把这两件事拆开**：配置文件里只有「用哪个 Python 跑哪个脚本」，令牌用
**Windows DPAPI 加密**存在 `~/.workbuddy/kingdee/club_token.bin`，运行时才读进内存。

---

## 能问什么

| 你说 | AI 做什么 |
|---|---|
| 「金蝶云星空结账提示『本期存在未记账凭证』怎么办？」 | 搜社区 → 给出处理步骤 + 原文链接 |
| 「单据转换规则在哪配？步骤说下」 | 找官方操作文档，按原文复述，不凭记忆编 |
| 「这个字段是什么意思？」 | 查字段说明与相关帖子，带出处 |
| 「升级到 V9 有没有已知问题？」 | 搜发版说明、补丁公告、踩坑帖 |
| 「社区里有人遇到过吗？」 | 返回帖子标题 + 摘要 + 链接，你自己决定点哪个 |

**它不做什么**：不碰你的账套、不读你的 Excel、不在社区发帖评论。只检索公开内容。
要查自己账套的数据，用 [金蝶云星空数据导出](https://github.com/LittleBeaverStudio/KingdeeDataExporter)。

> 能取到「摘要 + 链接」还是「整篇正文」，取决于服务端开放了哪些工具 ——
> 用 `python club_cli.py --tools` 看实时清单，以它为准。

---

## 🚀 三步开始

### 1. 录入令牌（弹窗，明文不落盘）

```bash
python setup_token.py
```

窗口里粘贴令牌 → 点「**测试连接**」（当场验证）→「保存并关闭」。

- 🔒 DPAPI 加密，绑当前 Windows 用户；同机其它用户读不出，拷到别的机器解不开
- 🔒 只显示尾 4 位，永不回显完整令牌；不写日志、不进对话
- 🔒 存在技能目录**之外**，升级 / 重装 / 打包都带不走
- 🔒 与「数据导出」的 `credentials.bin` 是两个文件，互不覆盖

令牌在哪拿：登录 `vip.kingdee.com` → 个人设置 / 访问令牌 → 创建「个人访问令牌（PAT）」。

没有图形环境？`python setup_token.py --console`（同样加密保存）。
只看状态：`--check`；删掉：`--delete`。

### 2. 自检

```bash
python club_cli.py --verify
```

```
服务地址  : https://vip.kingdee.com/api/mcp
令牌      : 加密凭据 club_token.bin（DPAPI）｜****9f2c
有效期    : 有效期至 2027-04-12 10:00（剩 165 天）
协议版本  : 2025-06-18
服务端    : kingdee-club ...
工具数量  : N
  · ...
✅ 连接正常。
```

### 3. 接进客户端

```bash
python club_cli.py --install-mcp                 # WorkBuddy（写入 ~/.workbuddy/mcp.json，自动备份）
python club_cli.py --install-mcp --client cursor # 或 trae / kiro / windsurf / claude / vscode / lingma
```

生成的就是普通 stdio MCP 配置，**里面没有令牌**：

```json
{
  "mcpServers": {
    "kingdee-club": {
      "command": "C:\\...\\python.exe",
      "args": ["C:\\...\\kingdee-club\\club_bridge.py"]
    }
  }
}
```

写完在客户端里点「**信任 / 启用**」，重启客户端。各客户端路径与入口见
[references/mcp-clients.md](./references/mcp-clients.md)。

> 不想改配置？直接用命令行：
> `python club_cli.py --tools` 看工具清单 → `python club_cli.py --call <工具> --args '{"query":"..."}'`

---

## 🧩 为什么令牌不写进 mcp.json

```
mcp.json        → 只有「哪个 Python 跑哪个脚本」，没有任何机密
club_token.bin  → DPAPI 密文（绑当前 Windows 用户）
运行期          → club_bridge.py 在内存里拼 Authorization 头
```

对客户端：它就是个标准 **stdio MCP 服务**（`initialize` / `tools/list` / `tools/call` 一个不少）。
对社区：它是一次标准 **HTTP MCP 会话**（Streamable HTTP + SSE，会话 ID 自动维护）。
行为完全一样，只是令牌不落盘。

官方 HTTP 直连写法仍然支持（如果你真要用），`--check` 会明确告警「该配置里有明文令牌」。

---

## 📋 命令表

| 命令 | 作用 |
|---|---|
| `python setup_token.py` | 令牌录入窗口（DPAPI 加密） |
| `python setup_token.py --check / --delete / --console` | 查状态 / 删除 / 文字向导 |
| `python club_cli.py --check` | 本地状态（令牌、有效期、MCP 配置），**不联网** |
| `python club_cli.py --verify` | 真实握手自检 |
| `python club_cli.py --tools [--json]` | 列出工具与参数 |
| `python club_cli.py --call <工具> --args '{...}'` | 直接调一个工具 |
| `python club_cli.py --mcp-config [--client X]` | 生成配置片段 |
| `python club_cli.py --install-mcp [--dry-run]` | 合并写入配置（自动备份） |
| `python club_cli.py --doctor` | 六步体检 |

**退出码**：`0` 成功 ｜ `2` 缺令牌 ｜ `3` 令牌被拒 ｜ `4` 网络 ｜ `5` 服务端/协议 ｜ `6` 工具错误。
（agent 按码判断，不要解析输出文字。）

---

## 🔒 安全边界

| 项目 | 说明 |
|---|---|
| 网络 | 只连 `vip.kingdee.com/api/mcp`（或你指定的 `--base-url`）；**不查更新、不报遥测** |
| 写文件 | 只写 `club_token.bin` 和（`--install-mcp` 时的）MCP 配置；改配置前自动备份 |
| 读文件 | 不读账套、Excel、发票；不碰 `credentials.bin` |
| 日志 | 只写 stderr，且不含令牌；stdout 留给 MCP 协议 |
| 子进程 | 仅在当前 Python 缺 tkinter 时，查找本机已装的另一个 Python 开窗（不装任何东西） |

---

## ❓ 常见问题

**Q：提示 401 `Malformed token`？**
令牌粘错或已过期。重跑 `setup_token.py`，粘完先点「测试连接」。

**Q：客户端里看不到工具？**
两件事：①在客户端点「信任 / 启用」（WorkBuddy 在连接器管理页）；②重启客户端。

**Q：换过 Python 之后 MCP 起不来了？**
配置里记的是旧解释器路径。重跑 `python club_cli.py --install-mcp`。

**Q：公司网络要走代理？**
设 `HTTPS_PROXY`；本机调试 mock 时把 `127.0.0.1` 加进 `NO_PROXY`。

**Q：支持 macOS / Linux 吗？**
桥和 CLI 是纯标准库、跨平台；但**加密存储只支持 Windows（DPAPI）**。
其它平台用环境变量 `KINGDEE_CLUB_TOKEN`（不落盘，但会进进程环境）。

更多报错对照见 [references/error-playbook.md](./references/error-playbook.md)。

---

## 🧱 为什么不用装依赖

`requirements.txt` 里只有注释 —— **零第三方包**。

MCP 官方 SDK 会拖进 pydantic / anyio / httpx 一串依赖，在很多财务同事的电脑上（受控内网、装过别家 Python、
pip 源不通）根本装不上。而本技能真正需要的只有「发 JSON、读 JSON/SSE」，
标准库的 `urllib` + `json` + `ctypes`（DPAPI）就够了。

---

小河狸工作室 LittleBeaverStudio · https://littlebeaver.top
