"""领域包：把「通用查证」变成「行业查证」的那一层配置。

设计取舍：不复制五份代码，只让领域包提供五类数据——
  1. 权威源分层（哪些站点在本行业算一手、哪些只能当消息源）
  2. 领域线索词（词表兜底时判断立场的行业特有表述）
  3. 语义上下文（告诉模型本行业的判定口径，比如「以官方原文为准，注意是否已废止」）
  4. 结论用语（财务说「与披露不符」，政策说「已废止」，法务说「存在地域差异」）
  5. 示例问句与关键字段（前端 chip 与卡片展示）

三层架构、权重公式、裁决门槛全部不动。新增一个行业 = 新增一个 JSON。
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field

DIR = pathlib.Path(__file__).resolve().parent / "domains"
_cache: dict[str, "Domain"] = {}


@dataclass
class Domain:
    id: str
    name: str
    tagline: str
    labels: dict[str, str] = field(default_factory=dict)
    tier_map: dict[str, int] = field(default_factory=dict)
    refute_cues: dict[str, int] = field(default_factory=dict)
    support_cues: dict[str, int] = field(default_factory=dict)
    semantic_context: str = ""
    queries: list[str] = field(default_factory=list)
    fields: list[str] = field(default_factory=list)
    disclaimer: str = ""
    # 法条、国标这类文本不按新闻时效衰减：2019 年发布的条文今天照样有效
    freshness_decay: bool = True

    def label(self, verdict: str, fallback: str) -> str:
        return self.labels.get(verdict) or fallback

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "tagline": self.tagline,
            "labels": self.labels,
            "fields": self.fields,
            "disclaimer": self.disclaimer,
        }


def _parse(raw: dict) -> Domain:
    tier_map: dict[str, int] = {}
    for tier_key, domains in (raw.get("authority") or {}).items():
        try:
            tier = int(tier_key.lstrip("t"))
        except ValueError:
            continue
        for suffix in domains or []:
            tier_map[str(suffix).lower()] = tier
    lexicon = raw.get("lexicon") or {}
    return Domain(
        id=str(raw["id"]),
        name=str(raw.get("name") or raw["id"]),
        tagline=str(raw.get("tagline") or ""),
        labels={str(k): str(v) for k, v in (raw.get("labels") or {}).items()},
        tier_map=tier_map,
        refute_cues={str(k): int(v) for k, v in (lexicon.get("refute") or {}).items()},
        support_cues={str(k): int(v) for k, v in (lexicon.get("support") or {}).items()},
        semantic_context=str(raw.get("semantic_context") or ""),
        queries=[str(q) for q in (raw.get("queries") or [])],
        fields=[str(f) for f in (raw.get("fields") or [])],
        disclaimer=str(raw.get("disclaimer") or ""),
        freshness_decay=bool(raw.get("freshness_decay", True)),
    )


def load(domain_id: str) -> Domain:
    domain_id = (domain_id or "general").strip().lower()
    if domain_id in _cache:
        return _cache[domain_id]
    path = DIR / f"{domain_id}.json"
    if not path.exists():
        path = DIR / "general.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    domain = _parse(raw)
    _cache[domain.id] = domain
    return domain


def list_domains() -> list[dict]:
    out: list[dict] = []
    for path in sorted(DIR.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        out.append({
            "id": raw.get("id"),
            "name": raw.get("name"),
            "tagline": raw.get("tagline"),
            "queries": raw.get("queries") or [],
        })
    general = [d for d in out if d["id"] == "general"]
    return general + [d for d in out if d["id"] != "general"]
