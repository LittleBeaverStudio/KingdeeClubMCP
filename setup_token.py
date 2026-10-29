# -*- coding: utf-8 -*-
"""金蝶云社区个人令牌录入向导 —— **明文不落盘**。

三条硬规矩（和「金蝶云星空数据导出」的凭据向导同一套）
──────────────────────────────────────────────────
1. **不经过对话**：令牌只在本地窗口里粘贴，不进聊天记录、不进 agent 的上下文；
2. **不落明文**：DPAPI 加密写入 `~/.workbuddy/kingdee/club_token.bin`，绑当前 Windows 用户；
3. **不回显、不写日志**：输入框掩码，只显示尾 4 位；任何输出都不含完整令牌。

用法
────
    python setup_token.py                # 打开配置窗口
    python setup_token.py --check        # 只看状态，不开窗
    python setup_token.py --delete       # 清除已保存令牌
    python setup_token.py --console      # 强制文字向导（排障用）
    python setup_token.py --probe-ui     # 只报告"会用哪个 Python 开窗"，不真开

退出码（agent 按码判断，不要猜输出文字）
────────────────────────────────────────
    0   已加密保存              10  用户取消 / 关窗（**没保存**，别盲目重跑）
    12  已有一个配置窗口开着     2   本机环境不支持 DPAPI
    3   保存失败                4   令牌格式明显不对（长度/空白）
"""

from __future__ import annotations

import argparse
import getpass
import os
import queue
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import clubstore  # noqa: E402

EXIT_OK = 0
EXIT_CANCELLED = 10
EXIT_BUSY = 12
EXIT_UNSUPPORTED = 2
EXIT_SAVE_FAILED = 3
EXIT_NEED_FALLBACK = 4

MIN_TOKEN_LEN = 16
IDLE_TIMEOUT_MS = 20 * 60 * 1000
LOCK_PATH = clubstore.STORE_DIR / ".club_setup.lock"
SELF = Path(__file__).resolve()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _sanitize(token: str) -> str:
    """去掉所有空白（从网页复制常带换行），并拒绝明显不是令牌的输入。"""
    return "".join((token or "").split())


def _validate(token: str) -> str | None:
    if not token:
        return "请先粘贴令牌。"
    if len(token) < MIN_TOKEN_LEN:
        return f"令牌长度只有 {len(token)} 位，看起来不完整（至少 {MIN_TOKEN_LEN} 位）。"
    if any(ord(ch) < 33 for ch in token):
        return "令牌里包含不可见字符，请重新复制。"
    return None


# ───────────────────────── 单实例锁（进程退出自动释放） ─────────────────────────

def _acquire_lock():
    try:
        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        handle = open(LOCK_PATH, "a+b")
    except OSError:
        return None
    try:
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def _release_lock(handle) -> None:
    if handle is None:
        return
    try:
        if sys.platform == "win32":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError:
        pass
    finally:
        handle.close()


# ─────────────────── 找一个"带 tkinter 的 Python"（零安装） ───────────────────

def _has_tkinter() -> bool:
    try:
        import tkinter  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def _probe(prefix: list[str]) -> bool:
    try:
        done = subprocess.run(prefix + ["-c", "import tkinter"],
                              capture_output=True, timeout=8)
        return done.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _iter_candidates():
    """产出候选解释器命令行（都不改系统 PATH、不装任何东西）。"""
    if sys.platform == "win32":
        yield ["py", "-3"]
        yield ["py"]
    for name in ("python3.13", "python3.12", "python3.11", "python3.10", "python3"):
        yield [name]
    if sys.platform == "win32":
        roots = []
        local = os.environ.get("LOCALAPPDATA")
        if local:
            roots.append(Path(local) / "Programs" / "Python")
        roots.append(Path("C:/"))
        for root in roots:
            if not root.is_dir():
                continue
            try:
                dirs = sorted((p for p in root.iterdir() if p.is_dir()), reverse=True)
            except OSError:
                continue
            for folder in dirs:
                exe = folder / "python.exe"
                if exe.is_file():
                    yield [str(exe)]


def _find_tkinter_python() -> list[str] | None:
    seen = {sys.executable.lower()}
    for candidate in _iter_candidates():
        key = candidate[0].lower()
        if key in seen:
            continue
        seen.add(key)
        if _probe(candidate):
            return candidate
    return None


def _relaunch(prefix: list[str]) -> int:
    cmd = prefix + [str(SELF), "--console" if "--console" in sys.argv else "--gui", "--no-relaunch"]
    try:
        return subprocess.run(cmd).returncode
    except OSError:
        return EXIT_NEED_FALLBACK


# ───────────────────────────── 图形界面（L0/L1） ─────────────────────────────

def _gui() -> int:
    try:
        import tkinter as tk
        from tkinter import messagebox, ttk
    except Exception:  # noqa: BLE001
        return EXIT_NEED_FALLBACK

    lock = _acquire_lock()
    if lock is None:
        return EXIT_BUSY

    state = {"token": None, "done": False, "base_url": ""}
    existing = clubstore.load() or {}

    root = tk.Tk()
    root.title("金蝶云社区 · 个人令牌")
    root.resizable(False, False)
    try:
        root.iconify()
        root.deiconify()
    except Exception:  # noqa: BLE001
        pass

    outer = ttk.Frame(root, padding=16)
    outer.pack(fill="both", expand=True)

    ttk.Label(outer, text="金蝶云社区个人令牌（PAT）",
              font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w")
    ttk.Label(outer, wraplength=520, justify="left", foreground="#555",
              text=("在 vip.kingdee.com 登录后，到「个人设置 → 访问令牌」创建或复制一个令牌，"
                    "整串粘贴到下面。令牌会用 Windows 系统加密（DPAPI）保存到\n"
                    "~/.workbuddy/kingdee/club_token.bin —— 不写明文、不进对话、不进 git，"
                    "mcp.json 里也不会出现它。")).pack(anchor="w", pady=(6, 12))

    form = ttk.Frame(outer)
    form.pack(fill="x")
    ttk.Label(form, text="令牌").grid(row=0, column=0, sticky="w", padx=(0, 8))

    token_var = tk.StringVar(value="")
    entry = ttk.Entry(form, textvariable=token_var, show="•", width=52)
    entry.grid(row=0, column=1, sticky="we")
    form.columnconfigure(1, weight=1)

    def toggle_show() -> None:
        entry.configure(show="" if show_var.get() else "•")

    show_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(form, text="显示", variable=show_var, command=toggle_show).grid(
        row=0, column=2, padx=(8, 0))

    ttk.Label(form, text="服务地址").grid(row=1, column=0, sticky="w", pady=(8, 0), padx=(0, 8))
    url_var = tk.StringVar(value=existing.get("base_url") or "https://vip.kingdee.com/api/mcp")
    url_entry = ttk.Entry(form, textvariable=url_var, width=52)
    url_entry.grid(row=1, column=1, sticky="we", pady=(8, 0))

    status_var = tk.StringVar(value=_status_line(existing))
    status = ttk.Label(outer, textvariable=status_var, wraplength=520, justify="left",
                       foreground="#1a6d1a")
    status.pack(anchor="w", pady=(12, 4))

    buttons = ttk.Frame(outer)
    buttons.pack(fill="x", pady=(12, 0))

    result = {"code": EXIT_CANCELLED}

    def set_status(text: str, ok: bool = True) -> None:
        status_var.set(text)
        status.configure(foreground="#1a6d1a" if ok else "#b00020")

    def test_connection() -> None:
        token = _sanitize(token_var.get())
        problem = _validate(token)
        if problem:
            set_status(problem, ok=False)
            return
        set_status("正在连接金蝶云社区…（最长 60 秒）")
        test_btn.configure(state="disabled")

        # 后台线程只做网络请求，结果经队列回到主线程再碰 Tk —— Tk 不是线程安全的，
        # 在子线程里直接 root.after / 改控件偶发会崩。
        results: "queue.Queue[tuple[str, bool]]" = queue.Queue()

        def worker() -> None:
            results.put(_probe_connection(token, url_var.get().strip()))

        def poll() -> None:
            try:
                message, ok = results.get_nowait()
            except queue.Empty:
                root.after(120, poll)
                return
            set_status(message, ok=ok)
            test_btn.configure(state="normal")

        threading.Thread(target=worker, daemon=True).start()
        root.after(120, poll)

    def save() -> None:
        token = _sanitize(token_var.get())
        problem = _validate(token)
        if problem:
            messagebox.showwarning("令牌不完整", problem, parent=root)
            return
        try:
            clubstore.save({
                "token": token,
                "saved_at": _now(),
                "base_url": url_var.get().strip() or "https://vip.kingdee.com/api/mcp",
            })
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("保存失败", f"{type(exc).__name__}: {exc}", parent=root)
            result["code"] = EXIT_SAVE_FAILED
            root.destroy()
            return
        result["code"] = EXIT_OK
        result["done"] = True
        messagebox.showinfo("已保存",
                            f"令牌已加密保存（{clubstore.mask(token)}）。\n\n"
                            "接下来：运行 python club_cli.py --mcp-config 生成 MCP 配置，"
                            "粘贴到你的 AI 客户端即可。", parent=root)
        root.destroy()

    def clear_saved() -> None:
        if not clubstore.exists():
            set_status("当前没有已保存的令牌。", ok=False)
            return
        if not messagebox.askyesno("清除令牌", "确定删除本机已保存的加密令牌？", parent=root):
            return
        clubstore.delete()
        set_status("已删除 club_token.bin。", ok=False)

    test_btn = ttk.Button(buttons, text="测试连接", command=test_connection)
    test_btn.pack(side="left")
    ttk.Button(buttons, text="保存并关闭", command=save).pack(side="left", padx=8)
    ttk.Button(buttons, text="清除已保存", command=clear_saved).pack(side="left")
    ttk.Button(buttons, text="取消", command=root.destroy).pack(side="right")

    def on_close() -> None:
        result["code"] = EXIT_OK if result["done"] else EXIT_CANCELLED
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.after(IDLE_TIMEOUT_MS, lambda: (set_status("空闲超时，已关闭（未保存）。", ok=False),
                                        root.after(1200, root.destroy)))
    entry.focus_set()
    root.mainloop()
    _release_lock(lock)
    return result["code"]


def _status_line(data: dict) -> str:
    if data.get("token"):
        return f"当前状态：{clubstore.describe(data)}"
    return "当前状态：未配置令牌（粘贴后点「保存并关闭」）"


def _probe_connection(token: str, base_url: str) -> tuple[str, bool]:
    """在后台线程里做一次真实握手：initialize + tools/list。"""
    import club_mcp
    try:
        client = club_mcp.McpClient(token=token, base_url=base_url, timeout=60)
        client.initialize()
        tools = client.list_tools()
        client.close()
    except club_mcp.TokenRejected as exc:
        return f"❌ {exc}", False
    except club_mcp.ClubError as exc:
        return f"❌ 连接失败：{exc}", False
    except Exception as exc:  # noqa: BLE001
        return f"❌ 未预期错误：{type(exc).__name__}: {exc}", False
    names = "、".join(t.get("name", "?") for t in tools[:6])
    more = f" 等 {len(tools)} 个" if len(tools) > 6 else f"，共 {len(tools)} 个"
    return f"✅ 连接成功：{names}{more}工具可用。", True


# ───────────────────────────── 文字向导（L3） ─────────────────────────────

def _console() -> int:
    lock = _acquire_lock()
    if lock is None:
        print("[!] 已有一个配置窗口开着，请先处理那个窗口。")
        return EXIT_BUSY
    try:
        existing = clubstore.load() or {}
        print("金蝶云社区个人令牌配置（输入不回显，Ctrl+C 取消）")
        print(f"当前状态：{clubstore.describe(existing)}")
        print("令牌获取：登录 vip.kingdee.com → 个人设置 → 访问令牌。")
        try:
            token = _sanitize(getpass.getpass("粘贴令牌: "))
        except (KeyboardInterrupt, EOFError):
            print("\n已取消，未保存。")
            return EXIT_CANCELLED
        problem = _validate(token)
        if problem:
            print(f"[!] {problem}")
            return EXIT_NEED_FALLBACK
        base_url = existing.get("base_url") or "https://vip.kingdee.com/api/mcp"
        message, ok = _probe_connection(token, base_url)
        print(message)
        if not ok:
            try:
                if input("连接没通过，仍要保存吗？[y/N] ").strip().lower() not in ("y", "yes"):
                    print("未保存。")
                    return EXIT_CANCELLED
            except (KeyboardInterrupt, EOFError):
                return EXIT_CANCELLED
        clubstore.save({"token": token, "saved_at": _now(), "base_url": base_url})
        print(f"✅ 已加密保存（{clubstore.mask(token)}）→ {clubstore.STORE_PATH}")
        return EXIT_OK
    except Exception as exc:  # noqa: BLE001
        print(f"[!] 保存失败：{type(exc).__name__}: {exc}")
        return EXIT_SAVE_FAILED
    finally:
        _release_lock(lock)


# ───────────────────────────── 启动器 ─────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="金蝶云社区个人令牌录入向导（DPAPI 加密，不落明文）")
    parser.add_argument("--check", action="store_true", help="只打印当前状态，不开窗")
    parser.add_argument("--delete", action="store_true", help="删除已保存的加密令牌")
    parser.add_argument("--console", action="store_true", help="强制文字向导")
    parser.add_argument("--gui", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--probe-ui", action="store_true", help="只报告会用什么解释器开窗")
    parser.add_argument("--no-relaunch", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.check:
        print("平台      :", sys.platform)
        print("DPAPI     :", "可用" if clubstore.available() else "不可用（非 Windows）")
        print("存储路径  :", clubstore.STORE_PATH)
        print("当前状态  :", clubstore.describe())
        if not clubstore.available():
            print("提示      : 非 Windows 请用环境变量 KINGDEE_CLUB_TOKEN")
        return EXIT_OK

    if args.delete:
        removed = clubstore.delete()
        print("已删除 club_token.bin" if removed else "没有已保存的令牌")
        return EXIT_OK

    if args.probe_ui:
        print("当前解释器      :", sys.executable, "tkinter:", _has_tkinter())
        found = _find_tkinter_python()
        print("将用于开窗的解释器:", found or "未找到（会退到文字向导）")
        return EXIT_OK

    if not clubstore.available():
        print("[!] 当前平台不支持 DPAPI 加密存储，无法保存令牌。")
        print("    请改用环境变量：KINGDEE_CLUB_TOKEN=<令牌>")
        return EXIT_UNSUPPORTED

    if args.console:
        return _console()

    if _has_tkinter():
        return _gui()
    if args.no_relaunch:
        return _console()
    prefix = _find_tkinter_python()
    if prefix:
        print(f"[i] 当前 Python 没有 tkinter，改用：{' '.join(prefix)}")
        code = _relaunch(prefix)
        if code != EXIT_NEED_FALLBACK:
            return code
    print("[i] 没找到带 tkinter 的解释器，改用文字向导。")
    return _console()


if __name__ == "__main__":
    sys.exit(main())
