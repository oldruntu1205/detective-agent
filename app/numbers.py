"""关键数字核对：同一张卡里，同一个量纲出现了不同数值就摆出来。

用户问的最多是「多少」，而「多少」最容易出错——口径不同、版本不同、单位串行。
这一步**不参与裁决**，只做提示：把不同来源里的数值按量纲并列，让人一眼看到分歧。

设计上刻意保守：
1. 只扫证据的触发原句（quote），不扫全文，避免把正文里的举例数字全部拉进来
2. 只处理有明确量纲的数值（金额 / 百分比 / 期限 / 倍数），无单位的裸数字一律忽略
3. 判定「有分歧」= 同一量纲归一后出现两个以上不同值；措辞只说「口径可能不同，请核对」，不说「矛盾」
4. 四位年份（1998 / 2026）不当期限处理

它回答的是「这张卡的数字经得起看吗」，而不是「哪个数字对」。哪个对，得人点开原文自己定。
"""

from __future__ import annotations

import re
from typing import Any

# (量纲, 正则, 单位换算到基准单位的系数, 基准单位)
PATTERNS: list[tuple[str, re.Pattern[str], dict[str, float], str]] = [
    (
        "金额",
        # 「万 / 亿」单独出现也算金额（中文常写「3000 万」），后面紧跟量词时排除
        re.compile(r"(\d+(?:\.\d+)?)\s*(亿元|万元|亿|万|元)(?!\s*(?:次|人|台|件|吨|公里|户|家|平))"),
        {"亿元": 100_000_000, "万元": 10_000, "亿": 100_000_000, "万": 10_000, "元": 1},
        "元",
    ),
    (
        "百分比",
        re.compile(r"(\d+(?:\.\d+)?)\s*(%|％)"),
        {"%": 1, "％": 1},
        "%",
    ),
    (
        "期限",
        re.compile(r"(\d+(?:\.\d+)?)\s*(个月|年|天|日)"),
        {"个月": 30, "年": 365, "天": 1, "日": 1},
        "天",
    ),
    (
        "倍数",
        re.compile(r"(\d+(?:\.\d+)?)\s*倍"),
        {"倍": 1},
        "倍",
    ),
]

DIM_LABEL = {"金额": "金额", "百分比": "百分比", "期限": "期限", "倍数": "倍数"}
_YEAR_LIKE = re.compile(r"(19|20)\d{2}")
_MONTH_BEFORE = re.compile(r"\d{1,2}\s*月\s*$")


def _is_date_fragment(quote: str, start: int, unit: str) -> bool:
    """「2025 年 6 月 18 日」里的 18 日是日期，不是「18 天」这种期限。"""
    if unit not in ("日", "天"):
        return False
    return bool(_MONTH_BEFORE.search(quote[:start]))


def _fmt_value(dim: str, raw: str, base: float) -> str:
    """把归一值还原成人能读的形式。"""
    if dim == "金额":
        if base >= 100_000_000:
            return f"{base / 100_000_000:g} 亿元"
        if base >= 10_000:
            return f"{base / 10_000:g} 万元"
        return f"{base:g} 元"
    if dim == "百分比":
        return f"{base:g}%"
    if dim == "期限":
        if base % 365 == 0 and base >= 365:
            return f"{base / 365:g} 年"
        if base % 30 == 0 and base >= 30:
            return f"{base / 30:g} 个月"
        return f"{base:g} 天"
    return raw


def _context(text: str, start: int, end: int, radius: int = 14) -> str:
    """截一段上下文，让数值脱离原文也看得懂在说什么。"""
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    snippet = text[left:right].replace("\n", " ").strip()
    return ("…" if left > 0 else "") + snippet + ("…" if right < len(text) else "")


def scan(evidence: list[Any]) -> list[dict[str, Any]]:
    """按量纲收集证据正文里的数值，返回存在分歧的量纲组。

    扫全文而不是只扫触发原句：用户问「补贴多少」时，答案那个数字常常不在
    决定立场的那一句里，只扫 quote 会系统性地漏掉它。
    """
    buckets: dict[str, list[dict[str, Any]]] = {}

    for item in evidence or []:
        hit = getattr(item, "hit", None)
        if hit is None:
            continue
        text = (getattr(hit, "passage", "") or getattr(hit, "content", "") or "")
        if not text:
            continue
        site = getattr(hit, "display_site", "")
        url = getattr(hit, "url", "")
        tier = getattr(hit, "tier", 4)
        stance = str(getattr(item, "stance", "") or "")

        for dim, pattern, scale, _base in PATTERNS:
            for matched in pattern.finditer(text):
                raw_num, raw_unit = matched.group(1), matched.group(2)
                if dim == "期限" and raw_unit == "年" and _YEAR_LIKE.fullmatch(raw_num):
                    continue  # 2008 年 这种是年份，不是期限
                if _is_date_fragment(text, matched.start(), raw_unit):
                    continue
                try:
                    value = float(raw_num) * scale[raw_unit]
                except (KeyError, ValueError):
                    continue
                if value <= 0:
                    continue
                buckets.setdefault(dim, []).append({
                    "value": value,
                    "raw": matched.group(0).strip(),
                    "shown": _fmt_value(dim, matched.group(0).strip(), value),
                    "ctx": _context(text, matched.start(), matched.end()),
                    "site": site,
                    "url": url,
                    "tier": tier,
                    "stance": stance,
                })

    groups: list[dict[str, Any]] = []
    for dim, items in buckets.items():
        distinct = {round(it["value"], 6) for it in items}
        if len(distinct) < 2:
            continue
        # 只有一个来源给出多个值时，多半是同一份材料在做口径对比（本期/上期/模拟口径），
        # 那是解释而不是分歧。必须跨来源才算「数字对不上」。
        if len({it["site"] for it in items}) < 2:
            continue

        # 同一来源重复给出同一个值时只留一条，且每个来源最多保留 2 条，避免一行被单个来源占满
        seen: set[tuple[float, str]] = set()
        per_site: dict[str, int] = {}
        values: list[dict[str, Any]] = []
        for it in sorted(items, key=lambda x: x["tier"]):
            key = (round(it["value"], 6), it["site"])
            if key in seen:
                continue
            if per_site.get(it["site"], 0) >= 2:
                continue
            seen.add(key)
            per_site[it["site"]] = per_site.get(it["site"], 0) + 1
            values.append({
                "raw": it["raw"],
                "shown": it["shown"],
                "ctx": it["ctx"],
                "site": it["site"],
                "url": it["url"],
                "stance": it["stance"],
            })

        groups.append({
            "dim": dim,
            "label": DIM_LABEL.get(dim, dim),
            "count": len(distinct),
            "sites": len({it["site"] for it in items}),
            "values": values[:6],
            "note": f"本卡里 {len({it['site'] for it in items})} 个来源给出了 {len(distinct)} 个不同的"
                    f"{DIM_LABEL.get(dim, dim)}数值，口径或版本可能不同，请点开原文核对后再引用。",
        })

    order = {"金额": 0, "百分比": 1, "期限": 2, "倍数": 3}
    groups.sort(key=lambda g: order.get(g["dim"], 9))
    return groups
