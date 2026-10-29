# 报错对照手册

按「你看到的原文 → 真正的原因 → 怎么做」查。所有条目都来自实际观测或协议规范，不是猜测。

---

## 一、认证类

### `HTTP 401` + `MCP endpoint requires authentication. Please provide a valid OAuth2 Bearer token or Personal Access Token (PAT).`

**原因**：请求没带 `Authorization` 头，或带了但值为空。
**做法**：说明令牌没读到。跑 `python setup_token.py --check` 看是否「未配置」；
若显示已配置，检查是不是用了 `--base-url` 指向了别的环境（令牌与地址要配套）。

### `HTTP 401` + `Invalid OAuth2 access token: ... decode the Jwt: Malformed token`

**原因**：令牌字符串本身不合法 —— 少复制了几位、带了换行、复制成了别的东西（比如密码、Cookie）。
**做法**：重跑 `python setup_token.py`，粘贴后**先点「测试连接」**再保存。
本技能会自动去掉复制时带进来的空格和换行，但**粘错内容**它救不了。

### `HTTP 401` + 令牌看起来完整、之前还能用

**原因**：令牌过期（社区令牌有有效期），或用户在社区后台把它吊销了。
**做法**：`python club_cli.py --check` 会打印「有效期至 …」；非 JWT 形态会显示「有效期未知」。
过期就去社区重新创建，再跑一次 `setup_token.py`。

### `HTTP 403`

**原因**：令牌有效，但账号/令牌没有该 MCP 服务的权限（社区侧授权范围问题）。
**做法**：这不是本技能能修的。去社区确认该令牌的权限范围，或换一个有权限的账号。
**不要反复重试** —— 403 重试不会变 200。

---

## 二、网络类

### `[WinError 10061] 由于目标计算机积极拒绝，无法连接`

**原因**：目标端口没有服务在听。多见于：`--base-url` 指向本机 mock 但 mock 没启动；
或公司网络把出站 443 拦了并返回 RST。
**做法**：先确认地址对不对；再 `curl -I https://vip.kingdee.com` 看通不通。

### `getaddrinfo failed` / `Name or service not known`

**原因**：DNS 解析失败。
**做法**：检查 DNS / hosts；如果用了代理，确认代理软件在运行。

### `Tunnel connection failed: 407` / `proxy`

**原因**：系统代理需要认证，或代理本身挂了。
**做法**：`set HTTPS_PROXY=http://user:pass@proxy:port` 后再试；或临时 `set HTTPS_PROXY=` 直连。

### `SSL: CERTIFICATE_VERIFY_FAILED`

**原因**：有中间人（企业安全软件、抓包代理）在拦 HTTPS，证书链不被信任。
**做法**：把企业根证书装进系统信任区，或换网络。**不要**为了绕过而关校验 ——
本技能没有关闭证书校验的开关，这是刻意的。

### 超时（`timed out`）

**原因**：链路慢，或社区侧检索耗时。
**做法**：`--call` 默认给 180 秒；仍超时就单独重试一次，并把服务端原文记下来。
MCP 客户端的单次工具超时通常比 180 秒短，客户端报超时不等于请求没成功。

---

## 三、配置类

### 客户端里根本看不到 `kingdee-club`

1. 配置写对了吗？`python club_cli.py --check` 会列出检测到的客户端与文件路径；
2. 点过「信任 / 启用」吗？WorkBuddy 必须在**连接器管理页**点一次「信任」，否则不加载；
3. 重启过客户端吗？多数客户端只在启动时读配置。

### `MCP server failed to start` / 客户端日志里是 `FileNotFoundError`

**原因**：`command` 或 `args` 里的路径不存在（换过 Python、挪过技能目录、从别的机器拷的配置）。
**做法**：重跑 `python club_cli.py --install-mcp`（会用当前解释器和当前路径重写）。

### 客户端日志里出现 `Unexpected token` / `Invalid JSON` / `Unexpected end of JSON input`

**原因**：有东西往 **stdout** 打了非协议内容，污染了 JSON-RPC 帧。
**做法**：本技能的桥在启动时已把真正的 stdout 单独持有、把 `sys.stdout` 改到 stderr，
正常情况下不会发生。若出现，检查是不是在 `club_bridge.py` 目录放了会 `print` 的 `sitecustomize.py`
或改了 `clubstore.py` 的输出。

### 工具调用返回「尚未配置金蝶云社区个人令牌」

**原因**：桥进程读不到令牌（用户在客户端启动后才配置，或配置在别的 Windows 用户下）。
**做法**：配好后**不用重启客户端**，再问一次即可（桥会重新读密文）；仍不行就重启客户端。

---

## 四、服务端 / 协议类

### `initialize` 返回 200 但没有 `Mcp-Session-Id`

**原因**：服务端不要求会话（无状态模式），或走了不兼容的网关。
**做法**：本技能对两种情况都兼容，不用处理。若后续请求返回 400 `missing session`，
说明会话头丢了 —— 检查是否有代理改写了响应头。

### `tools/list` 返回空数组

**原因**：该令牌能看到 0 个工具（权限范围问题），或服务端按账号灰度。
**做法**：`python club_cli.py --tools --json` 看原始响应；确认账号在社区有对应服务的访问权。

### `HTTP 400` + `missing session`

**原因**：`initialize` 之后没有带上 `Mcp-Session-Id`（自己写客户端时常见）。
**做法**：用本技能的 `club_bridge.py` / `club_mcp.py`，会话头是自动维护的。

### `HTTP 405 Method Not Allowed`

**原因**：用 GET 打开了 MCP 端点。MCP Streamable HTTP 只接受 POST（DELETE 用于结束会话）。
**做法**：用 `club_cli.py`，不要拿浏览器直接访问 `/api/mcp`。

---

## 五、判断顺序（别乱试）

```
python club_cli.py --check      ① 令牌有没有？MCP 配置在不在？        （不联网）
python club_cli.py --verify     ② 令牌 + 网络 + 协议 通不通            （一次握手）
python club_cli.py --doctor     ③ 六步定位，输出会直接告诉你是哪一环
```

排查顺序不要乱：**先看退出码**（0/2/3/4/5/6），再看服务端原文，最后才怀疑客户端。
不要一上来就重启 —— 退出码已经告诉你卡在哪一环。
