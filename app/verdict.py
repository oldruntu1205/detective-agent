"""裁决层：把一堆搜索结果变成一个结论 + 一条理由链。

设计原则（写进 README，也写在 UI 底部）：
  标签由可复现的加权规则产出，模型只负责表达。同一批输入永远得到同一个标签。

判定门槛与权重都在 config 里，可现场调参并复现。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from . import stance as stance_mod
from .authority import TIER_LABEL, classify, tier_weight
from .conditions import diff as condition_diff
from .config import config
from .gaps import build as build_gaps
from .models import Card, Evidence, STANCE_LABEL, VERDICT_LABEL, SearchHit
from .numbers import scan as scan_numbers
from .sources import mark_syndication

CLAIM_HINTS = ("是不是", "是否", "真的", "会致癌", "有毒", "安全吗", "能吃吗", "谣言",
               "靠谱吗", "可信吗", "会不会", "能不能", "有没有", "吗？", "吗?", "假的")
_DATE_RE = re.compile(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})")


def detect_mode(query: str) -> str:
    q = (query or "").strip()
    if any(h in q for h in CLAIM_HINTS):
        return "claim"
    if q.endswith("吗") or q.endswith("嘛"):
        return "claim"
    return "open"


def parse_date(raw: str) -> datetime | None:
    m = _DATE_RE.search(raw or "")
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def freshness_factor(raw: str, now: datetime) -> float:
    dt = parse_date(raw)
    if dt is None:
        return 0.95
    days = (now - dt).days
    if days < 0:
        return 1.0
    if days <= 30:
        return 1.10
    if days <= 365:
        return 1.00
    if days <= 365 * 3:
        return 0.90
    return 0.80


def annotate(hits: list[SearchHit], now: datetime,
             extra_tiers: dict[str, int] | None = None,
             freshness_decay: bool = True) -> list[SearchHit]:
    for hit in hits:
        domain, tier, label = classify(hit.url, hit.site, hit.authority_level, extra_tiers)
        hit.domain = domain
        hit.tier = tier
        hit.tier_label = label
        hit.freshness = freshness_factor(hit.date, now) if freshness_decay else 1.0
    return hits


def _dedupe(hits: list[SearchHit]) -> tuple[list[SearchHit], int]:
    """同一域名最多采信 config.max_per_domain 条，按相关性排序后取。"""
    hits = sorted(hits, key=lambda h: h.score, reverse=True)
    count: dict[str, int] = {}
    kept: list[SearchHit] = []
    dropped = 0
    for hit in hits:
        key = hit.domain or hit.url
        if count.get(key, 0) >= config.max_per_domain:
            dropped += 1
            continue
        count[key] = count.get(key, 0) + 1
        kept.append(hit)
    return kept, dropped


def build_evidence(hits: list[SearchHit], terms: list[str],
                   semantic: dict[int, dict] | None = None,
                   refute_add: dict[str, int] | None = None,
                   support_add: dict[str, int] | None = None) -> list[Evidence]:
    """逐条定性。semantic 里给了就用语义判定，没给或给了无效项就走词典法。"""
    board: list[Evidence] = []
    for idx, hit in enumerate(hits):
        judged = (semantic or {}).get(idx)
        if judged:
            st = str(judged.get("stance") or "neutral")
            quote = str(judged.get("quote") or "")
            reason = str(judged.get("reason") or "")
            by = "semantic"
        else:
            result = stance_mod.detect_stance(hit.text, terms, refute_add, support_add)
            st = str(result["stance"])
            quote = str(result["quote"])
            reason = ""
            by = "lexicon"
        if st not in STANCE_LABEL:
            st = "neutral"
        base = tier_weight(hit.tier) * (0.55 + 0.45 * min(max(hit.score, 0.0), 1.0)) * hit.freshness
        if hit.is_syndicated:
            base *= 0.5  # 转载不算独立印证，权重减半
        factor = {"support": 1.0, "refute": 1.0, "uncertain": 0.45, "neutral": 0.0}[st]
        board.append(
            Evidence(
                hit=hit,
                stance=st,
                stance_label=STANCE_LABEL[st],
                quote=quote,
                weight=base * factor,
                tier=hit.tier,
                tier_label=hit.tier_label,
                stance_by=by,
                stance_reason=reason,
            )
        )
    board.sort(key=lambda e: (e.tier, -e.weight))
    return board


def _fmt_sites(items: list[Evidence], limit: int = 3) -> str:
    names: list[str] = []
    for item in items:
        name = item.hit.display_site
        if name and name not in names:
            names.append(name)
    shown = "、".join(f"《{n}》" for n in names[:limit])
    if len(names) > limit:
        shown += f" 等 {len(names)} 家"
    return shown


def _first_sentence(text: str, limit: int = 110) -> str:
    for sentence in stance_mod.split_sentences(text):
        if len(sentence) >= 8:
            return sentence[:limit]
    return (text or "")[:limit]


def judge(query: str, hits: list[SearchHit], *, provider: str, elapsed_ms: int,
          notice: str = "", semantic_judge: object | None = None,
          domain: object | None = None) -> Card:
    now = datetime.now()
    mode = detect_mode(query)
    raw_count = len(hits)

    extra_tiers = getattr(domain, "tier_map", None) if domain else None
    decay = bool(getattr(domain, "freshness_decay", True)) if domain else True
    valid = [h for h in hits if h.score >= config.min_score and h.url.startswith("http")]
    hits_kept, dropped = _dedupe(valid)
    hits_kept = annotate(hits_kept, now, extra_tiers, decay)
    independent = mark_syndication(hits_kept)
    terms = stance_mod.claim_terms(query)

    semantic: dict[int, dict] = {}
    engine_note = ""
    if semantic_judge is not None and hasattr(semantic_judge, "classify"):
        semantic, engine_note = semantic_judge.classify(query, hits_kept)  # type: ignore[attr-defined]

    board = build_evidence(
        hits_kept, terms, semantic,
        refute_add=getattr(domain, "refute_cues", None) if domain else None,
        support_add=getattr(domain, "support_cues", None) if domain else None,
    )
    n_semantic = sum(1 for e in board if e.stance_by == "semantic")
    engine_name = "semantic" if n_semantic else "lexicon"

    card = Card(
        query=query,
        mode=mode,
        verdict="no_evidence",
        verdict_label=VERDICT_LABEL["no_evidence"],
        confidence=0.0,
        one_line="",
        evidence=board,
        query_time=now.strftime("%Y-%m-%d %H:%M:%S"),
        elapsed_ms=elapsed_ms,
        provider=provider,
        notice=notice,
        stats={
            "raw": raw_count,
            "used": len(hits_kept),
            "dropped": dropped + (raw_count - len(valid)),
            "judged": sum(1 for e in board if e.stance != "neutral"),
            "terms": terms[:8],
            "independent_sources": independent,
            "syndicated": sum(1 for h in hits_kept if h.is_syndicated),
            "engine": {
                "name": engine_name,
                "semantic": n_semantic,
                "lexicon": len(board) - n_semantic,
                "note": engine_note,
            },
        },
    )

    if not hits_kept:
        card.one_line = "这次没有检索到任何可用结果，所以不下结论。换个更具体的问法可以再试一次。"
        card.reasons = [
            f"检索返回 {raw_count} 条结果，可用（有链接、相关性 ≥ {config.min_score}）的为 0 条。",
            "按本工具规则：没有可点开的依据就不给结论，直接说『没查到可靠来源』。",
        ]
        return card

    if mode == "claim":
        _judge_claim(card, board)
    else:
        _judge_open(card, board, now)

    # 领域用语最后统一覆盖：财务说「与原始披露不符」，政策说「已废止」，法务说「存在地域差异」
    if domain is not None and hasattr(domain, "label"):
        card.verdict_label = domain.label(card.verdict, VERDICT_LABEL[card.verdict])  # type: ignore[attr-defined]
        card.domain = domain.to_dict()  # type: ignore[attr-defined]

    card.audit_steps = _audit_steps(card)
    robust = _robustness(card, board)
    if robust:
        card.stats["robustness"] = robust
        if robust["pivots"]:
            names = "、".join(f"《{p['site']}》" for p in robust["pivots"][:2])
            card.audit_steps.append(
                f"抽掉{names}再算一次，结论会翻——这张卡是它撑着的，先核对它。"
            )
        else:
            card.audit_steps.append(
                f"留一检验：把权重最高的 {robust['checked']} 条逐条抽掉重算，结论都不变，"
                "说明这张卡不是靠单条来源撑着的。"
            )

    # 关键数字核对：不参与裁决，只把同一量纲的不同数值摆出来
    card.numbers = scan_numbers(board)
    # 最小补证清单：把「还缺什么」变成可执行动作（依赖 stats / verdict，放在最后）
    card.gaps = build_gaps(card)
    return card


def _audit_steps(card: Card) -> list[str]:
    """给出「你可以这样推翻这张卡」的三步。可信度不该靠承诺，靠可复核。"""
    steps: list[str] = []
    evidence = card.evidence or []
    if not evidence:
        return [
            "换一个更具体的问法再查一次——这次没有检索到可用来源，不代表这件事不存在。",
            "如果你手上有官方文件或权威链接，直接以那份材料为准。",
            "本卡没有结论，不存在被推翻的结论。",
        ]

    primary = min(evidence, key=lambda e: (e.tier, -e.weight))
    quote = primary.quote[:40] + ("…" if len(primary.quote) > 40 else "")
    steps.append(
        f"点开《{primary.hit.display_site}》原文，核对这句话是否原样存在：「{quote}」"
    )

    # 只有和对立面（support ↔ refute）才算反方；同侧来源不构成反驳
    opposite = "refute" if primary.stance == "support" else "support"
    rivals = [e for e in evidence if e.stance == opposite and e.hit.url != primary.hit.url]

    if card.conflicts:
        steps.append("点开冲突双方原文各读一遍，确认它们讨论的确实是同一件事、同一个条件。")
    elif rivals:
        rival = rivals[0]
        steps.append(
            f"点开反方《{rival.hit.display_site}》看它为什么没被采信——原话是「{rival.quote[:30]}」，"
            "如果它其实更权威或更新，这张卡的结论就该改。"
        )
    else:
        steps.append("把这句话自己拿去搜一次，特别是搜「辟谣」「官方回应」，看有没有更新的说法。")

    if primary.hit.is_syndicated:
        steps.append(f"核对转载关系：这条本身就转载自《{primary.hit.syndicated_site}》，先读原始那篇。")
    elif card.mode == "claim":
        steps.append("找一条发布时间更近的同级来源。本卡里最新的证据时间是 "
                     f"{primary.hit.date or '未标注'}，更晚的官方表态优先。")
    else:
        steps.append("这一条是开放式提问，没有真假结论；把它当作检索入口，点开原文自行判断。")
    return steps


def _label_from(w_support: float, w_refute: float) -> str:
    """只看权重合计给标签，与 _judge_claim 的门槛保持一致（供留一检验复用）。"""
    total = w_support + w_refute
    if total < config.min_evidence_weight:
        return "no_evidence"
    ratio = max(w_support, w_refute) / total
    if w_support >= 0.6 and w_refute >= 0.6 and ratio < config.conflict_ratio:
        return "unclear"
    return "true" if w_support >= w_refute else "false"


def _robustness(card: Card, board: list[Evidence]) -> dict:
    """留一检验：逐条抽掉权重最高的几条，看结论会不会翻。

    回答的是「这张卡是不是只靠一根柱子撑着」——比再给一个置信度百分比有用。
    """
    if card.mode != "claim" or card.verdict not in ("true", "false"):
        return {}
    candidates = [e for e in board if e.stance in ("support", "refute")]
    top = sorted(candidates, key=lambda e: -e.weight)[:3]
    pivots: list[dict] = []
    for item in top:
        rest = [x for x in board if x is not item]
        w_s = sum(x.weight for x in rest if x.stance == "support")
        w_r = sum(x.weight for x in rest if x.stance == "refute")
        if _label_from(w_s, w_r) != card.verdict:
            pivots.append({
                "site": item.hit.display_site,
                "url": item.hit.url,
                "weight": round(item.weight, 2),
            })
    return {"checked": len(top), "pivots": pivots}


def _judge_claim(card: Card, board: list[Evidence]) -> None:
    support = [e for e in board if e.stance == "support"]
    refute = [e for e in board if e.stance == "refute"]
    uncertain = [e for e in board if e.stance == "uncertain"]
    w_support = sum(e.weight for e in support)
    w_refute = sum(e.weight for e in refute)
    total = w_support + w_refute

    card.stats.update({
        "weight_support": round(w_support, 2),
        "weight_refute": round(w_refute, 2),
        "threshold": config.min_evidence_weight,
    })

    if total < config.min_evidence_weight:
        card.verdict = "no_evidence"
        card.verdict_label = VERDICT_LABEL["no_evidence"]
        card.one_line = "现有的信息里找不到能定性这句话的依据，所以我不会给你一个『看起来很像』的答案。"
        card.reasons = [
            f"共检索 {card.stats['used']} 条结果，其中 {len(support) + len(refute)} 条带有可判定的表述。",
            f"支持与否定两方的权重合计仅 {total:.2f}，低于判定门槛 {config.min_evidence_weight:.2f}。",
            f"存疑类表述 {len(uncertain)} 条（{_fmt_sites(uncertain) or '无'}）。",
            "按本工具规则：证据不足时只说『没查到可靠来源』，不猜。",
        ]
        if uncertain:
            card.reasons.append("存疑表述示例：" + uncertain[0].quote)
        return

    ratio = max(w_support, w_refute) / total
    winner_is_support = w_support >= w_refute
    win_label = "支持该说法" if winner_is_support else "否定该说法"

    low_both = w_support >= 0.6 and w_refute >= 0.6 and ratio < config.conflict_ratio
    if low_both:
        card.verdict = "unclear"
        card.verdict_label = VERDICT_LABEL["unclear"]
        card.confidence = 0.0
        side_a, side_b = (support, refute) if winner_is_support else (refute, support)
        side_a_label = "支持该说法" if winner_is_support else "否定该说法"
        side_b_label = "否定该说法" if winner_is_support else "支持该说法"
        card.one_line = "两种说法都有来源，而且都够权威、权重量级接近，这件事没法一句话定性。"
        card.conflicts = [
            {"side": side_a_label, "weight": round(sum(e.weight for e in side_a), 2),
             "items": [e.to_dict() for e in side_a[:3]]},
            {"side": side_b_label, "weight": round(sum(e.weight for e in side_b), 2),
             "items": [e.to_dict() for e in side_b[:3]]},
        ]
        # 冲突双方的限定条件差异：这一步把「说不准」再往前推一层
        cond = condition_diff(side_a[0].quote, side_b[0].quote)
        if cond.get("differ"):
            cond["side_a"] = side_a_label
            cond["side_b"] = side_b_label
            card.condition_diff = cond
        card.reasons = [
            f"两方证据权重比为 {w_support:.2f} : {w_refute:.2f}，差距 {abs(1 - ratio) * 100:.0f}%，未达到可定性的门槛。",
            f"多数一方：{_fmt_sites(side_a)}；反方：{_fmt_sites(side_b)}。",
            "冲突点：" + side_a[0].quote + " ↔ " + side_b[0].quote,
            "按本工具规则：权威源正面冲突时不站队，明确告诉你『说不准』，并列出双方原话供你自己判断。",
        ]
        if cond.get("differ"):
            card.reasons.append(cond["note"])
        return

    winners = support if winner_is_support else refute
    losers = refute if winner_is_support else support
    card.verdict = "true" if winner_is_support else "false"
    card.verdict_label = VERDICT_LABEL[card.verdict]

    top_tier = min(e.tier for e in winners)
    confidence = ratio
    if top_tier == 1:
        confidence += 0.08
    elif top_tier == 3:
        confidence -= 0.10
    elif top_tier == 4:
        confidence -= 0.22
    if len({e.hit.domain for e in winners}) == 1:
        confidence -= 0.08
    card.confidence = max(0.2, min(0.95, confidence))

    w_win = max(w_support, w_refute)
    w_lose = min(w_support, w_refute)
    top = winners[0]
    card.one_line = _first_sentence(top.quote)
    card.reasons = [
        f"共采信 {card.stats['used']} 条结果，其中 {len(support) + len(refute)} 条带有明确表述，正反权重 {w_support:.2f} : {w_refute:.2f}。",
        f"结论一边（{win_label}）的权重合计 {w_win:.2f}，主要来源：{_fmt_sites(winners)}。",
        f"最高权威来源为{top.tier_label}《{top.hit.display_site}》"
        + (f"，发布于 {top.hit.date}" if top.hit.date else "")
        + f"，原文：『{top.quote}』",
    ]
    if w_lose > 0:
        card.reasons.append(
            f"反方 {len(losers)} 条、权重 {w_lose:.2f}，主要来源：{_fmt_sites(losers)}；"
            f"按权威度分级（T1 > T2 > T3 > T4）未采信其结论。"
        )
    if top_tier > 1:
        card.reasons.append(
            f"注意：本次未采信到 T1 权威一手来源，结论依赖 {top.tier_label}，置信度已相应下调。"
        )
    if len({e.hit.domain for e in winners}) == 1:
        card.reasons.append("有效来源集中在单一站点，独立交叉验证不足，置信度已下调。")
    if len(winners) >= 3:
        card.reasons.append(f"结论一边由 {len({e.hit.domain for e in winners})} 个独立域名交叉支撑。")


def _judge_open(card: Card, board: list[Evidence], now: datetime) -> None:
    """查最新 / 查模糊：不判真假，给要点 + 来源可追溯。"""
    # 开放式提问没有「支持/否定」之分，按权威档 + 相关性排序，不按立场权重
    ranked = sorted(board, key=lambda e: (e.tier, -e.hit.score))
    relevant = [e for e in ranked if e.hit.score >= config.min_score_open]
    usable = [e for e in relevant if e.tier <= 3] or relevant
    top_score = max((e.hit.score for e in ranked), default=0.0)

    if not usable:
        card.verdict = "no_evidence"
        card.verdict_label = VERDICT_LABEL["no_evidence"]
        card.one_line = "检索到的内容都和这个问题对不上，所以我不猜。"
        card.reasons = [
            f"共检索 {card.stats['used']} 条结果，最高相关性仅 {top_score:.2f}，低于判定门槛 {config.min_score_open:.2f}。",
            "命中的都是背景资料或相邻话题，没有一条直接回答提问。",
            "按本工具规则：证据不足时只说『没查到可靠来源』，不用模型记忆补答案。",
        ]
        return

    card.verdict = "found"
    card.verdict_label = VERDICT_LABEL["found"]
    primary = usable[0]
    card.one_line = _first_sentence(primary.hit.passage or primary.hit.content or primary.hit.title)

    seen: set[str] = set()
    for item in usable:
        if item.hit.domain in seen:
            continue
        seen.add(item.hit.domain)
        card.key_facts.append({
            "text": _first_sentence(item.hit.passage or item.hit.content or item.hit.title, 140),
            "site": item.hit.display_site,
            "url": item.hit.url,
            "date": item.hit.date,
            "tier": item.tier,
            "tier_label": item.tier_label,
        })
        if len(card.key_facts) >= 3:
            break

    domains = len({e.hit.domain for e in usable})
    card.confidence = max(0.25, min(0.9, 0.45 + 0.12 * min(domains, 4) + (0.1 if primary.tier == 1 else 0)))
    card.reasons = [
        f"共采信 {card.stats['used']} 条结果，覆盖 {domains} 个独立域名。",
        f"首要来源：{primary.tier_label}《{primary.hit.display_site}》"
        + (f"，发布于 {primary.hit.date}" if primary.hit.date else "（未标注发布时间）"),
        f"检索时间 {now.strftime('%Y-%m-%d %H:%M')}，以上要点均可在右侧原文中点开核对。",
    ]
    if primary.tier >= 3:
        card.reasons.append("首要来源权威度偏低，建议点开原文与更权威来源交叉核对。")
    if domains == 1:
        card.reasons.append("仅命中单一站点，未形成交叉验证。")
