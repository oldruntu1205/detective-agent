"""配置读取：环境变量优先，其次项目根目录 .env。零第三方依赖。"""

from __future__ import annotations

import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_env(path: pathlib.Path | None = None) -> None:
    p = path or (ROOT / ".env")
    if not p.exists():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


class Config:
    def __init__(self) -> None:
        load_env()
        self.secret_id = os.environ.get("TENCENTCLOUD_SECRET_ID", "").strip()
        self.secret_key = os.environ.get("TENCENTCLOUD_SECRET_KEY", "").strip()
        self.region = os.environ.get("TENCENTCLOUD_REGION", "").strip()
        self.mode = _int("WSA_MODE", 2)
        self.cnt = _int("WSA_CNT", 10)
        self.freshness = os.environ.get("WSA_FRESHNESS", "").strip()
        self.industry = os.environ.get("WSA_INDUSTRY", "").strip()
        self.provider = os.environ.get("PROVIDER", "auto").strip().lower()
        self.stance_engine = os.environ.get("STANCE_ENGINE", "auto").strip().lower()
        self.llm_base_url = os.environ.get("LLM_BASE_URL", "").rstrip("/")
        self.llm_api_key = os.environ.get("LLM_API_KEY", "").strip()
        self.llm_model = os.environ.get("LLM_MODEL", "").strip()
        self.llm_timeout = _int("LLM_TIMEOUT", 25)
        self.host = os.environ.get("HOST", "127.0.0.1").strip()
        self.port = _int("PORT", 8765)

        # 裁决参数（可解释、可复现，改动请同步 README 的调参表）
        self.min_score = 0.15          # 低于此相关性直接丢弃
        self.min_score_open = 0.50      # 开放式问题（查最新/查模糊）的最低相关性，避免拿擦边结果凑答案
        self.min_evidence_weight = 1.0  # 有效证据权重下限，低于此判定「没查到可靠来源」
        self.conflict_ratio = 0.68      # 双方权重占比都超过该阈值时判为「说不准」
        self.max_per_domain = 2         # 同一域名最多采信条数，避免单一站点刷权重

    @property
    def has_wsa(self) -> bool:
        return bool(self.secret_id and self.secret_key)

    @property
    def has_llm(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key and self.llm_model)

    @property
    def resolved_provider(self) -> str:
        """返回本次实际使用的检索层。"""
        if self.provider in ("wsa", "mock"):
            return self.provider
        return "wsa" if self.has_wsa else "mock"

    @property
    def resolved_stance_engine(self) -> str:
        """姿态判定引擎：semantic（语义）/ lexicon（词典兜底）。"""
        if self.stance_engine == "lexicon":
            return "lexicon"
        if self.stance_engine == "semantic":
            return "semantic"
        return "semantic" if self.has_llm else "lexicon"


config = Config()
