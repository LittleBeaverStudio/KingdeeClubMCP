---
name: kingdee-club
slug: kingdee-club
displayName: 金蝶云社区问答
version: 1.0.0
description: 连接金蝶云社区（vip.kingdee.com）官方 MCP：在对话里搜社区帖子与官方知识文档，查金蝶云星空 / 苍穹的报错原因、操作步骤、字段含义、版本已知问题，不用再开浏览器翻论坛。个人令牌用 Windows DPAPI 加密存本机（不写明文、不进对话、不进 mcp.json），支持 WorkBuddy / Cursor / Claude 等 8 种客户端。当用户问「金蝶报错 XX 怎么办」「这个功能怎么操作」时使用。
license: 小河狸非转售许可 1.0（企业内部使用免费，转售收费需授权）
---

## 许可与使用范围

本 Skill 采用「小河狸工作室非转售许可 1.0」，完整条款见本目录 `LICENSE`。

- ✅ **免费使用**：个人学习 / 研究 / 个人事务；**企业内部使用**——某一组织为其自身业务运营而使用
  （内部办公、财务与会计处理、内部管理与报表、内部系统集成），同一控股关联实体视同内部使用。
- ✅ 可为上述用途自行修改本 Skill。
- ❌ **须另行取得书面授权**：对外销售、出租、许可；集成进对外收费的产品或服务；托管 / SaaS / 代运营；
  打包进收费课程、付费社群或付费安装包；收费的实施与咨询培训；**以及利用本 Skill 向本组织之外的第三方交付成果或提供服务**。
- 📌 区分标准只有一条：**是否以本 Skill 向本组织之外的第三方交付成果或提供服务**。
- 📌 再分发须保留本许可、版权声明与来源：小河狸工作室 LittleBeaverStudio · https://littlebeaver.top

商业授权申请：https://littlebeaver.top（邮箱 yk.niu@outlook.com）

---

# 金蝶云社区问答

把**金蝶云社区（vip.kingdee.com）的官方 MCP 服务**接进 AI 客户端：不用切浏览器、不用在论坛里翻页，
直接把「这个报错什么意思」「这个功能怎么点」「有没有人遇到过」丢给 AI，它去社区里找**原文**并给出处。

本 Skill 解决的是**接入**这一层，而不是复刻社区数据：

- 生成 / 写入各客户端的 MCP 配置（8 种客户端）；
- 用 **Windows DPAPI 加密**保管个人令牌，**不写明文、不进对话、不落日志**；
- 提供 `--verify` 自检、`--tools` 工具清单、`--call` 直调、`--doctor` 六步体检；
- 提供一个 **stdio 桥**，让 `mcp.json` 里**根本不出现令牌**（这是和官方 `headers` 写法的核心差别）。

> **关于平台「需配置 API Key」标签**：本 Skill **不需要去开放平台申请任何 Key**。
> 你只需要**自己的金蝶云社区账号**里的一个「个人访问令牌（PAT）」，在弹窗里粘一次即可；
> 令牌加密存在技能目录之外，升级 / 重装都不会带走。

---

## 什么时候用它

| 用户的说法 | 这个技能能做什么 |
|---|---|
| 「金蝶云星空结账提示『本期存在未记账凭证』怎么办？」 | 搜社区，把官方/高赞处理步骤和原文链接带回来 |
| 「单据转换规则在哪里配？步骤说下」 | 找官方操作文档，按原文复述步骤，不凭记忆编 |
| 「这个字段/参数是什么意思？」 | 查字段说明与相关帖子，给出出处 |
| 「升级到某版本有没有已知问题？」 | 搜发版说明、补丁公告、踩坑帖 |
| 「社区里有人遇到过这个问题吗？」 | 返回相关帖子标题 + 摘要 + 链接，由用户决定点哪个 |

**不适合**：查自己账套里的业务数据（用 `kingdee-data-exporter`）、做经营分析（用 `kingdee-data-analyzer`）、
发起报销（用 `kingdee-expense-flow`）。本技能只读社区公开内容，**不碰你的账套**。

> 能取到「摘要 + 链接」还是「整篇正文」，取决于服务端当前开放了哪些工具 —— 以
> `python club_cli.py --tools` 的实时输出为准，不要在文档里写死工具名或字段。

---

## 🚀 首次使用：三步

### 第 1 步：录入令牌（**必须用户自己在电脑上操作**）

```bash
python setup_token.py
```

会弹出一个窗口，把令牌粘进去 → 点「测试连接」（当场验证能不能通）→「保存并关闭」。
令牌用 **Windows 系统加密（DPAPI）** 保存到 `~/.workbuddy/kingdee/club_token.bin`：

- 🔒 绑当前 Windows 用户 —— 同机其它用户读不出，拷到别的机器解不开；
- 🔒 不在技能目录里，升级 / 重装 / 打包都带不走；
- 🔒 只显示尾 4 位，**永不回显完整令牌**、不写日志、不进对话；
- 🔒 与「金蝶云星空数据导出」的 `credentials.bin` **是两个文件**，互不覆盖。

> 🤖 **给 agent 的硬规矩（务必遵守）**
> 1. **绝不向用户索要令牌**，也不要让用户把令牌发到对话里 —— 令牌只在本地窗口输入；
> 2. **绝不代写** `club_token.bin`、`config.json` 或任何含令牌的文件；
> 3. 用户说「没有令牌」时，告诉他去 `vip.kingdee.com` 登录后在**个人设置 / 访问令牌**里创建，
>    然后回来跑 `python setup_token.py`；
> 4. 判断配置是否成功**只看退出码和 `--check` 输出**，不要猜。

只看状态（不开窗、不联网）：`python setup_token.py --check`
删除已保存令牌：`python setup_token.py --delete`
没有图形环境时：`python setup_token.py --console`（密码式输入，同样加密保存）

**退出码**：`0` 已保存 ｜ `10` 用户取消（**没保存**，别盲目重跑）｜ `12` 已有一个窗口开着
｜ `2` 本机不支持 DPAPI（改用环境变量）｜ `3` 保存失败 ｜ `4` 令牌格式明显不对

### 第 2 步：连接自检

```bash
python club_cli.py --verify
```

真实握手一次（`initialize` + `tools/list`），打印：服务地址、令牌来源与尾号、有效期、协议版本、
服务端名称、工具数量与逐个说明。看到 `✅ 连接正常` 就说明令牌和网络都没问题。

### 第 3 步：接进你的 AI 客户端（二选一）

**A. 接入 MCP（推荐，一次配置，之后在对话里直接调工具）**

```bash
python club_cli.py --mcp-config                 # 打印 WorkBuddy 的配置片段
python club_cli.py --install-mcp                # 或直接合并写入 ~/.workbuddy/mcp.json（自动备份）
python club_cli.py --mcp-config --client cursor # 其它客户端：cursor/trae/kiro/windsurf/claude/vscode/lingma
```

生成的条目长这样 —— **注意里面没有令牌**：

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

写完后：在客户端的 MCP / 连接器页面**点「信任」或「启用」**（WorkBuddy 在连接器管理页），然后重启客户端。
各客户端的配置文件位置与操作路径见 `references/mcp-clients.md`。

**B. 命令行直调（不改配置、不用重启，适合临时用和排障）**

```bash
python club_cli.py --tools                                     # 先看有哪些工具、参数是什么
python club_cli.py --call <工具名> --args '{"query":"结账 未记账凭证"}'
```

> 工具名与参数**以 `--tools` 的实时输出为准**，不要凭记忆写死 —— 服务端升级可能调整。

---

## 为什么 `mcp.json` 里没有令牌

金蝶云社区官方文档的写法是把令牌直接写进配置：

```json
{"mcpServers": {"kingdee-club": {"type": "http", "url": "https://vip.kingdee.com/api/mcp",
  "headers": {"Authorization": "Bearer <你的个人令牌>"}}}}
```

这样能通，但令牌是**明文摊在磁盘上**的：截图、网盘同步、发同事排障、误提交 git，任何一次都等于泄露。
本 Skill 改成 **stdio 桥**：

```
mcp.json       → 只有「用哪个 python 跑哪个脚本」，没有机密
club_token.bin → DPAPI 密文，绑当前 Windows 用户
运行期         → 令牌只在 club_bridge.py 进程内存里拼进 Authorization 头
```

对客户端来说它仍是一个标准 stdio MCP 服务（`initialize` / `tools/list` / `tools/call` 全都照常），
对金蝶云社区来说仍是一次标准 HTTP MCP 会话 —— **行为不变，只是令牌不再落盘**。

> 如果你更想用官方 `headers` 写法：可以，但那是你的选择，`--doctor` 会明确告警「该配置里有明文令牌」。

---

## 常用命令

| 命令 | 用途 |
|---|---|
| `python setup_token.py` | 打开令牌录入窗口（DPAPI 加密保存） |
| `python setup_token.py --check / --delete` | 只看状态 / 删除已保存令牌 |
| `python club_cli.py --check` | 本地状态：令牌、有效期、MCP 配置是否就绪（**不联网**） |
| `python club_cli.py --verify` | 真实连接自检（initialize + tools/list） |
| `python club_cli.py --tools [--json]` | 列出服务端工具与参数 |
| `python club_cli.py --call <工具> --args '{...}' [--json]` | 直接调用一个工具 |
| `python club_cli.py --mcp-config [--client X]` | 生成 MCP 配置片段（不含令牌） |
| `python club_cli.py --install-mcp [--dry-run]` | 合并写入配置文件（自动备份原文件） |
| `python club_cli.py --doctor` | 六步体检：环境 → 令牌 → 端点 → 握手 → 配置 → 结论 |

**退出码（按码判断，不要猜输出文字）**

| 码 | 含义 | 该做什么 |
|---|---|---|
| 0 | 成功 | — |
| 2 | 缺少令牌 | 让用户跑 `python setup_token.py` |
| 3 | 令牌被拒（401/403） | 换一个新令牌；403 还要看该账号有没有该 MCP 的权限 |
| 4 | 网络 / 代理不可达 | 查网络、DNS、系统代理 |
| 5 | 服务端错误 / 协议错误 | 稍后重试；持续失败看 `references/error-playbook.md` |
| 6 | 工具执行返回错误 | 看返回文本，多半是参数不对 |

---

## 环境变量（可选）

| 变量 | 作用 |
|---|---|
| `KINGDEE_CLUB_TOKEN` | 直接提供令牌（CI / 无人值守）。**优先级高于密文**，注意它不落盘但会进进程环境 |
| `KINGDEE_CLUB_MCP_URL` | 覆盖服务地址（默认 `https://vip.kingdee.com/api/mcp`） |
| `HTTPS_PROXY` / `NO_PROXY` | 走公司代理时用；`NO_PROXY` 里加 `127.0.0.1` 可避免本机 mock 被代理劫持 |

**读取优先级：命令行参数 > 环境变量 > DPAPI 密文。** 三者都没有就报「缺少令牌」，不会去猜。

---

## 权限与行为声明

- **网络访问**：只访问 `https://vip.kingdee.com/api/mcp`（或你显式指定的 `--base-url` / `KINGDEE_CLUB_MCP_URL`），
  请求头里带 `Authorization: Bearer <你的令牌>`。**不访问 GitHub、不上报任何遥测、不检查更新。**
- **本地文件读写**：
  - 写 `~/.workbuddy/kingdee/club_token.bin`（DPAPI 密文，唯一写入者是 `setup_token.py`）；
  - `--install-mcp` 时读写客户端的 MCP 配置文件（默认 `~/.workbuddy/mcp.json`），**写前自动备份** `*.bak-<时间戳>`；
  - 不读你的 Excel、账套、发票，也不碰 `credentials.bin`。
- **子进程**：`setup_token.py` 在当前 Python 没有 tkinter 时，会**查找本机已装的另一个 Python** 来开窗
  （不改 PATH、不静默安装任何东西）；`club_bridge.py` 由 MCP 客户端启动。
- **环境变量**：见上表，仅三个。
- **不回显敏感信息**：令牌只显示尾 4 位；日志只出现在 stderr，且不含令牌。
- **只读社区**：本技能不会在社区发帖、评论、点赞、下载附件。

---

## 排障

| 现象 | 原因 / 处理 |
|---|---|
| `--verify` 报 401 `Malformed token` | 令牌粘错或已过期。重跑 `setup_token.py` 换新令牌（窗口里先点「测试连接」） |
| `--verify` 报 403 | 账号没有该 MCP 服务权限，去社区确认令牌权限范围 |
| `--verify` 报「域名解析失败 / 连接超时」 | 网络或公司代理。先 `curl https://vip.kingdee.com` 试试，必要时设 `HTTPS_PROXY` |
| 客户端里看不到 `kingdee-club` 工具 | 没点「信任 / 启用」，或没重启客户端；WorkBuddy 在**连接器管理页右上角**点「信任」 |
| 客户端报「MCP server failed to start」 | 跑 `python club_cli.py --doctor`，看桥脚本路径与 Python 路径是否存在（换过 Python 会失效，重跑 `--install-mcp`） |
| 工具调用超时 | 社区检索偶尔较慢；桥对 `tools/call` 给到 180 秒，仍超时用 `--call` 单独重试看服务端原文 |
| `--check` 显示「含明文令牌」 | 你之前按官方写法把令牌写进过 `mcp.json`；跑 `--install-mcp` 覆盖该条目，并**去社区重置令牌** |

更细的报错对照见 `references/error-playbook.md`。

---

## 与其它金蝶技能的关系

| 技能 | 负责什么 | 是否需要凭据 |
|---|---|---|
| **kingdee-club**（本技能） | 查社区知识、报错、操作步骤 | 社区个人令牌（DPAPI 密文） |
| `kingdee-data-exporter` | 从**你自己的账套**取数导出 Excel | 金蝶账号密码（DPAPI 密文） |
| `kingdee-data-analyzer` | 销售 / 采购 / 存货经营分析 | 零凭据（调 exporter 或读 Excel） |
| `kingdee-expense-flow` | 费用 / 差旅报销全流程 | 金蝶账号 + 发票云授权 |

四个技能各写各的密文文件，**任何一个升级都不会冲掉别人的配置**。
