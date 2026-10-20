"""最小补证清单：把「没查到」从一个负结论，变成一个可执行的动作。

「敢说不知道」是这套东西最值钱的镜头，但只停在认输有点浪费——
用户真正想知道的是「那我还要拿到什么，这事才能定」。

这里按「这张卡缺什么」逐项生成补证建议，全部是可验证的具体动作，不说空话：

| 缺什么 | 补什么 |
|---|---|
| 没有 T1 权威一手来源 | 找一份主管部门原文 / 原始披露 / 现行标准文本 |
| 来源集中在单一域名 | 换一个独立域名交叉验证 |
| 存在转载 | 找到被转载的原始那篇 |
| 证据整体偏旧 | 找一份发布时间在 X 之后的来源 |
| 关键来源没标时间 | 找一条带发布时间的来源 |
| 结论说不准 | 找双方各自的适用范围说明 |
| 没查到 | 把问题问得更具体（地区 / 年份 / 型号 / 版本） |

只输出 3~4 条：多了用户不会做，等于没给。
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

_DATE_RE = re.compile(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})")


def _parse_date(raw: str) -> datetime | None:
    m = _DATE_RE.search(raw or "")
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def build(card: Any) -> list[str]:
    """根据这张卡的实际缺口，给出补证清单。"""
    evidence = list(getattr(card, "evidence", []) or [])
    stats = dict(getattr(card, "stats", {}) or {})
    domain = getattr(card, "domain", {}) or {}
    verdict = str(getattr(card, "verdict", "") or "")
    gaps: list[str] = []

    tiers = [e.tier for e in evidence]
    sites = {e.hit.display_site for e in evidence if e.hit.display_site}
    domains = {e.hit.domain for e in evidence if e.hit.domain}
    dated = [_parse_date(e.hit.date) for e in evidence]
    dated = [d for d in dated if d]
    now = datetime.now()

    # 1. 权威档：没有一手来源时，这是最该补的一项
    if evidence and min(tiers) > 1:
        gaps.append(
            f"补一份 T1 权威一手来源——政府或主管部门原文、原始披露文件、现行标准文本，"
            f"或这个问题对口的权威一手发布渠道。目前最高只采信到 T{min(tiers)} 档。"
        )

    # 2. 独立性：单一站点 / 转载
    if len(domains) == 1:
        gaps.append(
            "换一个独立域名再查一次：现在所有证据都来自同一个站点，"
            "没有形成交叉验证，同一个站点的两篇文章不算两个来源。"
        )
    origins = {
        e.hit.syndicated_site for e in evidence
        if getattr(e.hit, "is_syndicated", False) and e.hit.syndicated_site
    }
    missing_origins = origins - sites
    if missing_origins:
        gaps.append(
            f"找到被转载的原始那篇（{('、'.join(sorted(missing_origins)))[:40]}）："
            "只拿到转载稿时，没法确认原文里有没有被删掉的限定条件。"
        )

    # 3. 时效：整体偏旧或关键来源没标时间
    decay = bool(domain.get("freshness_decay", True))
    if evidence and decay and dated:
        newest = max(dated)
        age_days = (now - newest).days
        if age_days > 365 * 2:
            gaps.append(
                f"找一份发布时间在 {newest.strftime('%Y-%m')} 之后的来源："
                f"本卡最新的证据也已经 {age_days // 365} 年了，口径可能已经变过。"
            )
    if evidence and any(not e.hit.date for e in evidence) and len(gaps) < 3:
        gaps.append("补一条标注了发布时间的来源——没有时间就没法判断它是不是已经被更新过的版本覆盖。")

    # 4. 终态相关：说不准 / 没查到，各自补的东西不一样
    if verdict == "unclear":
        gaps.append(
            "找双方的适用范围说明（各自在什么人群、剂量、场景下成立）："
            "这类争议多数不是谁造假，而是两句话的条件不同。"
        )
    elif verdict == "no_evidence":
        gaps.append(
            "把问题问得更具体再查：加上地区、年份、型号或版本，"
            "「没有可判定的材料」很多时候是因为问得太宽，检索捞不到针对性材料。"
        )

    # 5. 查真假但缺反方：单向证据最容易翻车
    if verdict in ("true", "false"):
        stances = {e.stance for e in evidence}
        if not ({"support", "refute"} <= stances):
            gaps.append(
                "主动找一条反方说法来试：本卡只采信到一边的证据，"
                "没有遇到像样的反驳意见，这种情况下最容易漏掉反例。"
            )

    if not gaps:
        indie = stats.get("independent_sources") or len(sites)
        gaps.append(
            f"这张卡没有硬缺口（{len(evidence)} 条证据、{indie} 个独立来源、最高 T{min(tiers) if tiers else '-'} 档）。"
            "真要再验一次，就自己把它拿去搜「辟谣」和「官方回应」两路——"
            "这两路都找不到反对意见，它才暂时站得住。"
        )

    return gaps[:4]
