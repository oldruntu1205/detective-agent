"""独立来源识别：把「转载」和「独立报道」分开。

要解决的问题很具体：搜索出来 5 家媒体都在说同一句话，很容易被当成「5 个独立来源交叉验证」，
实际上可能只是同一条通稿被转了 5 次。这里用字符三元组相似度做近似判重，
同源的后到者在权重上打折，并在卡片上标出「转载自 X」。

不做的事：不做全文去重（没有原文正文），只用标题 + 摘要开头做近似判断，
所以阈值放宽（0.55），宁可漏判同源，也不要把不同的报道误判成转载。
"""

from __future__ import annotations

import re

from .models import SearchHit

_CJK = re.compile(r"[^\u4e00-\u9fa5A-Za-z0-9]+")
THRESHOLD = 0.55
HEAD = 140


def _grams(text: str, n: int = 3) -> set[str]:
    clean = _CJK.sub("", text or "")
    if len(clean) < n:
        return {clean} if clean else set()
    return {clean[i:i + n] for i in range(len(clean) - n + 1)}


def _similarity(a: SearchHit, b: SearchHit) -> float:
    ga = _grams(f"{a.title}{a.passage[:HEAD]}")
    gb = _grams(f"{b.title}{b.passage[:HEAD]}")
    if not ga or not gb:
        return 0.0
    inter = len(ga & gb)
    union = len(ga | gb)
    return inter / union if union else 0.0


def mark_syndication(hits: list[SearchHit]) -> int:
    """就地标记同源关系，返回独立来源数量。

    规则：按权威度优先（tier 小者优先）、其次相关性排序，先到者为「原始」，
    后来者若与任一已确认原始高度相似，则标为转载并指向原始。
    """
    ordered = sorted(hits, key=lambda h: (h.tier, -h.score))
    primaries: list[SearchHit] = []
    for hit in ordered:
        origin = next((p for p in primaries if _similarity(hit, p) >= THRESHOLD), None)
        if origin is None:
            primaries.append(hit)
            continue
        hit.is_syndicated = True
        hit.syndicated_of = origin.url
        hit.syndicated_site = origin.display_site
    return len(primaries)
