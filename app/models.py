"""数据结构：搜索结果 → 证据 → 查证卡。"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class SearchHit:
    """元宝搜索返回的单条结果（已解析 Pages 里的 JSON 字符串）。"""

    title: str
    url: str
    site: str = ""
    date: str = ""
    passage: str = ""
    content: str = ""
    score: float = 0.0
    authority_level: int | None = None
    favicon: str = ""

    # 检索层之后填充的派生字段
    domain: str = ""
    tier: int = 4
    tier_label: str = ""
    freshness: float = 1.0

    # 多路检索与同源识别
    via: str = ""                  # 这条结果由哪一路查询捞回来的
    is_syndicated: bool = False     # 是否判定为转载
    syndicated_of: str = ""         # 转载的原始链接
    syndicated_site: str = ""       # 转载的原始站点

    @property
    def text(self) -> str:
        body = self.passage or self.content
        return f"{self.title}。{body}" if self.title and body else (self.title or body)

    @property
    def display_site(self) -> str:
        return self.site or self.domain

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Evidence:
    """进入裁决板的一条证据。"""

    hit: SearchHit
    stance: str            # support / refute / uncertain / neutral
    stance_label: str
    quote: str             # 触发判定的原文句子
    weight: float          # 该证据在裁决中的权重
    tier: int
    tier_label: str
    stance_by: str = "lexicon"    # semantic / lexicon：这条立场是谁判的
    stance_reason: str = ""       # 语义判定给出的短理由

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.hit.title,
            "url": self.hit.url,
            "site": self.hit.display_site,
            "domain": self.hit.domain,
            "date": self.hit.date,
            "quote": self.quote,
            "stance": self.stance,
            "stance_label": self.stance_label,
            "stance_by": self.stance_by,
            "stance_reason": self.stance_reason,
            "tier": self.tier,
            "tier_label": self.tier_label,
            "score": round(self.hit.score, 4),
            "weight": round(self.weight, 3),
            "via": self.hit.via,
            "is_syndicated": self.hit.is_syndicated,
            "syndicated_site": self.hit.syndicated_site,
        }


STANCE_LABEL = {
    "support": "支持该说法",
    "refute": "否定该说法",
    "uncertain": "存疑 / 尚无定论",
    "neutral": "仅陈述事实",
}

VERDICT_LABEL = {
    "true": "真",
    "false": "假",
    "unclear": "说不准",
    "no_evidence": "没查到可靠来源",
    "found": "已查到",
    "error": "查询失败",
}


@dataclass
class Card:
    """一次查证的完整结果，直接序列化成前端渲染用的 JSON。"""

    query: str
    mode: str                       # claim（查真假）/ open（查最新、查模糊）
    verdict: str
    verdict_label: str
    confidence: float
    one_line: str
    reasons: list[str] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    key_facts: list[dict[str, Any]] = field(default_factory=list)
    query_time: str = ""
    elapsed_ms: int = 0
    provider: str = "mock"
    notice: str = ""
    stats: dict[str, Any] = field(default_factory=dict)
    domain: dict[str, Any] = field(default_factory=dict)
    audit_steps: list[str] = field(default_factory=list)   # 三步推翻路径
    condition_diff: dict[str, Any] = field(default_factory=dict)  # 冲突双方的条件差异
    numbers: list[dict[str, Any]] = field(default_factory=list)   # 关键数字核对（不参与裁决）
    gaps: list[str] = field(default_factory=list)                 # 最小补证清单
    related: list[dict[str, Any]] = field(default_factory=list)  # 相近内容：不是答案，仅参考
    version: str = ""                                             # 产出这张卡的规则版本

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "mode": self.mode,
            "verdict": self.verdict,
            "verdict_label": self.verdict_label,
            "confidence": round(self.confidence, 3),
            "one_line": self.one_line,
            "reasons": self.reasons,
            "conflicts": self.conflicts,
            "evidence": [e.to_dict() for e in self.evidence],
            "key_facts": self.key_facts,
            "query_time": self.query_time,
            "elapsed_ms": self.elapsed_ms,
            "provider": self.provider,
            "notice": self.notice,
            "stats": self.stats,
            "domain": self.domain,
            "audit_steps": self.audit_steps,
            "condition_diff": self.condition_diff,
            "numbers": self.numbers,
            "gaps": self.gaps,
            "related": self.related,
            "version": self.version,
        }
