# -*- coding: utf-8 -*-
"""金蝶云社区令牌的加密存储（Windows DPAPI，**纯标准库**）。

为什么单独一个文件
──────────────────
`~/.workbuddy/kingdee/credentials.bin` 是「金蝶云星空连接凭据」的唯一写入者
（由 `kingdee-data-exporter` 的配置向导写），本技能**不读、不写、不覆盖**它。
原因很实际：两个技能共用一个密文文件时，谁后保存谁就把对方的配置整份替换掉。

本模块只写 `~/.workbuddy/kingdee/club_token.bin`，内容就三项：
`token`（社区个人令牌）、`saved_at`（保存时间）、`base_url`（服务地址）。

为什么不做明文配置
──────────────────
令牌等价于「以你的身份读社区」的凭证。明文落盘会顺着 git、压缩包、截图、日志、
网盘备份一路外泄，而且事后无法追溯。所以本技能**不提供任何明文令牌配置文件**：

  · 首选 —— DPAPI 密文（本模块），绑当前 Windows 用户；
  · 例外 —— 当前进程的环境变量 `KINGDEE_CLUB_TOKEN`（CI / 无人值守用，不落盘）；
  · 不提供 —— `config.json` / `config.py` 里写 token 的写法（想写也没处读）。

保护到什么程度
──────────────
· 按**当前 Windows 登录用户**派生密钥：同机其它用户读不出，拷贝到别的机器解不开；
· 固定 entropy（写在源码里，不是密钥）：防止同机其它程序捡到密文直接 `CryptUnprotectData`；
· 调用带 `CRYPTPROTECT_UI_FORBIDDEN`：绝不弹系统对话框（无人值守必须）；
· 原子替换写入，权限尽量收紧到 0600；
· 本模块**不打印任何明文**；`describe()` 只回报「有没有配置 + 尾号 4 位」。

非 Windows
──────────
`available()` 返回 False。此时只能走环境变量，调用方应给出明确提示，**不要报错崩掉**。
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
from ctypes import wintypes
from pathlib import Path

# ── 落盘位置（技能目录之外：升级 / 重装 / 打包都不会覆盖或带走）──
STORE_DIR = Path.home() / ".workbuddy" / "kingdee"
STORE_PATH = STORE_DIR / "club_token.bin"

# 固定 entropy：与 exporter 的 credentials.bin **不同**，两份密文互不通用
_ENTROPY = b"kingdee-club-token-v1"


# ─────────────────────────── DPAPI 绑定 ───────────────────────────

class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.c_void_p)]


def _bind():
    """加载 crypt32/kernel32 并声明签名；非 Windows 返回 (None, None)。"""
    if sys.platform != "win32":
        return None, None
    try:
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    except OSError:
        return None, None

    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB), wintypes.LPCWSTR, ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DATA_BLOB),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB), ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DATA_BLOB), ctypes.c_void_p, ctypes.c_void_p,
        wintypes.DWORD, ctypes.POINTER(_DATA_BLOB),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    return crypt32, kernel32


_CRYPT32, _KERNEL32 = _bind()

CRYPTPROTECT_UI_FORBIDDEN = 0x1


def _blob(data: bytes):
    """构造 DATA_BLOB；返回 (blob, 持有人)，持有人必须存活到调用结束。"""
    keeper = ctypes.create_string_buffer(data, len(data))
    return _DATA_BLOB(len(data), ctypes.cast(keeper, ctypes.c_void_p)), keeper


def _take(blob: _DATA_BLOB) -> bytes:
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        if blob.pbData:
            _KERNEL32.LocalFree(blob.pbData)


def _protect(data: bytes) -> bytes:
    in_blob, keep1 = _blob(data)
    ent_blob, keep2 = _blob(_ENTROPY)
    out = _DATA_BLOB()
    ok = _CRYPT32.CryptProtectData(
        ctypes.byref(in_blob), None, ctypes.byref(ent_blob),
        None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out),
    )
    del keep1, keep2
    if not ok:
        raise OSError(ctypes.get_last_error(), "CryptProtectData 失败")
    return _take(out)


def _unprotect(blob: bytes) -> bytes:
    in_blob, keep1 = _blob(blob)
    ent_blob, keep2 = _blob(_ENTROPY)
    out = _DATA_BLOB()
    ok = _CRYPT32.CryptUnprotectData(
        ctypes.byref(in_blob), None, ctypes.byref(ent_blob),
        None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out),
    )
    del keep1, keep2
    if not ok:
        raise OSError(ctypes.get_last_error(), "CryptUnprotectData 失败（密文不属于当前用户 / 已损坏）")
    return _take(out)


# ─────────────────────────── 对外 API ───────────────────────────

def available() -> bool:
    """当前环境能否使用 DPAPI 加密存储。"""
    return _CRYPT32 is not None


def exists() -> bool:
    return STORE_PATH.is_file()


def save(payload: dict) -> None:
    """把 dict 加密写入 club_token.bin（原子替换，权限尽量收紧）。"""
    if not available():
        raise RuntimeError("当前平台不支持 DPAPI，无法使用加密凭据存储（请改用环境变量 KINGDEE_CLUB_TOKEN）")
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    blob = _protect(raw)
    tmp = STORE_PATH.with_suffix(".bin.tmp")
    with open(tmp, "wb") as fh:
        fh.write(blob)
    os.replace(tmp, STORE_PATH)
    try:  # 尽力收紧权限（NTFS 上失败也不影响加密保护）
        os.chmod(STORE_PATH, 0o600)
    except OSError:
        pass


def load() -> dict | None:
    """读取并解密；无文件返回 None；密文不可解时返回 None。

    注意：警告一律写 **stderr** —— 本模块会被 stdio 桥调用，往 stdout 打一个字
    就会破坏 MCP 的 JSON-RPC 协议帧。
    """
    if not available() or not exists():
        return None
    try:
        blob = STORE_PATH.read_bytes()
    except OSError:
        return None
    if not blob:
        return None
    try:
        raw = _unprotect(blob)
    except OSError:
        print("[WARN] 加密令牌无法解密（可能换了 Windows 用户或拷自别的机器），"
              "请重新运行 setup_token.py", file=sys.stderr)
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        print("[WARN] 加密令牌文件损坏，请重新运行 setup_token.py", file=sys.stderr)
        return None
    return data if isinstance(data, dict) else None


def delete() -> bool:
    """删除加密令牌文件；存在并删除成功返回 True。"""
    if not exists():
        return False
    try:
        STORE_PATH.unlink()
        return True
    except OSError:
        return False


def mask(token: str) -> str:
    """只露尾 4 位，长度够才露；其余用固定长度省略。"""
    token = (token or "").strip()
    if not token:
        return "（空）"
    if len(token) <= 8:
        return "****"
    return "****" + token[-4:]


def describe(data: dict | None = None) -> str:
    """回报「是否已配置 + 尾号 + 保存时间」，**绝不回显令牌本身**。"""
    if data is None:
        data = load()
    if not data or not data.get("token"):
        return "未配置（club_token.bin 不存在或为空）"
    tip = mask(data.get("token"))
    when = data.get("saved_at") or "未知时间"
    return f"已配置 {tip} ｜ 保存于 {when}"


if __name__ == "__main__":  # 自检：加解密往返 + 损坏密文，不落盘
    print("平台        :", sys.platform)
    print("DPAPI 可用  :", available())
    if available():
        probe = {"token": "自检用临时值-not-a-real-token", "saved_at": "self-test"}
        blob = _protect(json.dumps(probe).encode("utf-8"))
        back = json.loads(_unprotect(blob).decode("utf-8"))
        print("往返一致    :", back == probe)
        try:
            _unprotect(b"\x00" * 32)
            print("损坏密文    : ❌ 竟然解开了")
        except OSError:
            print("损坏密文    : ✅ 解密失败（符合预期）")
        print("存储路径    :", STORE_PATH)
        print("当前状态    :", describe())
    else:
        print("提示        : 非 Windows，请用环境变量 KINGDEE_CLUB_TOKEN")
