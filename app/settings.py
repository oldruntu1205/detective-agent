"""元宝搜索密钥的本地存取：读 / 写项目根的 .env，热更新当前进程的 config。

为什么不用数据库、不用系统钥匙串：
这个项目的定位是「拷走就能跑」，配置只有两把密钥。放在项目根的 `.env`（已在 `.gitignore` 里）
是最不会出事的方式——看得见、能自己核对、删掉就干净。界面上填一次，等价于手工编辑 .env，
区别只是不用记变量名、且保存时顺手探一次连通性。

三条边界：
1. **只写 .env，不写别处**，不留其它副本。
2. **不回显完整密钥**：查询接口只返回脱敏值（`AKID****wxyz`）和「SecretKey 已保存」。
3. **改完立刻生效**：同步更新 `os.environ` 与 `config` 单例，不要求重启服务。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .config import ROOT, config

ENV_PATH: Path = ROOT / ".env"
ENV_EXAMPLE: Path = ROOT / ".env.example"

SID_KEY = "TENCENTCLOUD_SECRET_ID"
SKEY_KEY = "TENCENTCLOUD_SECRET_KEY"
PROVIDER_KEY = "PROVIDER"

_HEADER = "# ===== 元宝搜索（腾讯云 wsa / SearchPro）====="
_MINIMAL_TEMPLATE = (
    _HEADER + "\n"
    "# 控制台取密钥：https://console.cloud.tencent.com/cam/capi\n"
    f"{SID_KEY}=\n{SKEY_KEY}=\n"
)

MAX_LEN = 256
_KEY_LINE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")


# ---------- 脱敏 ----------

def mask_secret_id(value: str) -> str:
    """SecretId 不是高敏，但也没必要整串回显。"""
    v = (value or "").strip()
    if not v:
        return ""
    if len(v) <= 8:
        return "*" * len(v)
    return f"{v[:4]}{'*' * 6}{v[-4:]}"


def mask_secret_key(value: str) -> str:
    return "已保存" if (value or "").strip() else ""


# ---------- .env 读写 ----------

def _read_lines() -> list[str]:
    if not ENV_PATH.exists():
        base = ENV_EXAMPLE if ENV_EXAMPLE.exists() else None
        text = base.read_text(encoding="utf-8") if base else _MINIMAL_TEMPLATE
        return text.splitlines()
    return ENV_PATH.read_text(encoding="utf-8").splitlines()


def _write_lines(lines: list[str]) -> None:
    """统一 LF 收尾，避免在 Windows 上被翻成 CRLF 后 git 一直报「已修改」。"""
    body = "\n".join(lines).rstrip("\n") + "\n"
    with open(ENV_PATH, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(body)


def _upsert(lines: list[str], key: str, value: str) -> list[str]:
    """改已有行；没有就追加在文件末尾（缺 header 时先补 header）。"""
    for i, line in enumerate(lines):
        m = _KEY_LINE.match(line)
        if m and m.group(1) == key:
            lines[i] = f"{key}={value}"
            return lines
    if not any(l.strip() == _HEADER for l in lines):
        lines.extend(["", _HEADER, "# 控制台取密钥：https://console.cloud.tencent.com/cam/capi"])
    lines.append(f"{key}={value}")
    return lines


def file_values() -> dict[str, str]:
    """只解析 .env 里的键值，不做任何副作用。"""
    out: dict[str, str] = {}
    try:
        for line in _read_lines():
            m = _KEY_LINE.match(line)
            if m:
                out[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def _apply(secret_id: str, secret_key: str) -> None:
    """同步到环境变量与 config 单例——pipeline 下次查证就能用上新密钥。"""
    os.environ[SID_KEY] = secret_id
    os.environ[SKEY_KEY] = secret_key
    config.secret_id = secret_id
    config.secret_key = secret_key


def _apply_provider(value: str) -> None:
    os.environ[PROVIDER_KEY] = value
    config.provider = value


# ---------- 对外接口 ----------

def status() -> dict:
    """给界面看的状态。**不含任何完整密钥。**"""
    vals = file_values()
    sid = (config.secret_id or "").strip()
    if vals.get(SID_KEY) and vals.get(SID_KEY) == sid:
        source = "file"
    elif sid:
        source = "env"
    else:
        source = "none"
    return {
        "has_wsa": config.has_wsa,
        "provider": config.resolved_provider,
        "provider_setting": config.provider,
        "secret_id_masked": mask_secret_id(sid),
        "secret_key_set": bool((config.secret_key or "").strip()),
        "source": source,
        "env_path": str(ENV_PATH),
        "env_exists": ENV_PATH.exists(),
        "forced_mock": config.provider == "mock",
    }


def looks_like_secret_id(value: str) -> bool:
    """腾讯云 SecretId 一般是 AKID + 32 位。这里只做「像不像」的软校验，不拦人。"""
    v = (value or "").strip()
    return v.startswith("AKID") and len(v) >= 20


def save(secret_id: str, secret_key: str) -> dict:
    """写入 .env → 热更新 → 返回新状态。调用方负责参数校验。"""
    sid = (secret_id or "").strip().strip('"').strip("'")
    skey = (secret_key or "").strip().strip('"').strip("'")
    lines = _read_lines()
    lines = _upsert(lines, SID_KEY, sid)
    lines = _upsert(lines, SKEY_KEY, skey)
    notes: list[str] = []

    # PROVIDER=mock 是演示用的强制开关。用户既然亲手填了密钥，就说明想看实时检索，
    # 于是顺手改回 auto —— 但要在结果里讲明白，不能让配置被悄悄改掉。
    if config.provider == "mock":
        lines = _upsert(lines, PROVIDER_KEY, "auto")
        _apply_provider("auto")
        notes.append("检测到 PROVIDER=mock（强制离线），已改为 auto，保存后即走实时检索")
    elif config.provider == "wsa":
        notes.append("PROVIDER=wsa（强制实时）：密钥不可用时查证会直接报错，不会退回离线样例")

    _write_lines(lines)
    _apply(sid, skey)
    return {"status": status(), "notes": notes}


def clear() -> dict:
    """清空两把密钥并回落到离线样例。.env 里其它配置原样保留。"""
    lines = _upsert(_read_lines(), SID_KEY, "")
    lines = _upsert(lines, SKEY_KEY, "")
    if config.provider in ("mock", "wsa"):
        lines = _upsert(lines, PROVIDER_KEY, "auto")
        _apply_provider("auto")
    _write_lines(lines)
    _apply("", "")
    return {"status": status(), "notes": ["已清除密钥，检索层回到离线样例"]}


def probe(secret_id: str, secret_key: str, timeout: int = 12) -> dict:
    """用刚填的密钥真打一次 SearchPro，把结果翻译成一句人话。

    故意不复用 pipeline：这里只需要「通不通」，不需要分级、裁决、出卡。
    """
    from .providers.base import SearchError
    from .providers.tencent_wsa import TencentWsaProvider

    try:
        hits = TencentWsaProvider(
            secret_id, secret_key,
            region=config.region, mode=config.mode, cnt=10, timeout=timeout,
        ).search("腾讯云")
    except SearchError as exc:
        return {"ok": False, "message": _humanize(str(exc))}
    except Exception as exc:  # noqa: BLE001 网络层的意外不该让保存动作失败
        return {"ok": False, "message": f"{type(exc).__name__}: {exc}"}
    sample = ""
    if hits:
        sample = hits[0].site or hits[0].title or ""
    return {
        "ok": True,
        "message": f"连通正常，返回 {len(hits)} 条结果" + (f"（示例站点：{sample}）" if sample else ""),
        "hits": len(hits),
    }


def _humanize(message: str) -> str:
    """把云厂商错误码翻成能照着做的下一步。原文附在后面，不吞掉。

    顺序要紧：「SecretIdNotFound」里也含 notfound，不能先按「未开通服务」处理，
    否则密钥填错的人会被指去开通服务，白跑一趟。
    """
    low = message.lower()
    if "resourcenotfound" in low or "notenough" in low or "notopen" in low:
        return f"密钥有效，但元宝搜索服务未开通——去控制台开通后再试。原文：{message}"
    if "authfailure" in low or "secretidnotfound" in low or "signature" in low \
            or "unauthorized" in low or "invalidsecret" in low:
        return f"密钥校验失败：SecretId / SecretKey 不匹配、已禁用或已删除，重新生成一对再试。原文：{message}"
    if "requestlimitexceeded" in low:
        return f"密钥有效，但当前触发限频，稍等片刻再试。原文：{message}"
    if "无法连接" in message or "超时" in message:
        return f"网络不通，密钥没能验证（已保存，可稍后再试）。原文：{message}"
    return message
