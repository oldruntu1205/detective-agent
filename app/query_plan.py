"""多路查询规划：一次查证，跑几路不同的问法。

为什么需要：单路检索天然偏向「和用户问法相似」的结果，容易只捞到同温层证据。
辟谣类内容往往不会用提问的方式写标题，所以必须主动构造反向、官方、时效三路查询。

这一步是确定性的（不依赖模型），保证同一句话每次跑出的查询集合一致，结果可复现。
"""

from __future__ import annotations

import re
from datetime import datetime

QUESTION_RE = re.compile(
    r"(是不是|是否|真的|到底|究竟|会不会|有没有|能不能|可不可以|请问|帮我|查一下|麻烦|吗|呢|吧|\?|？)"
)


def core_claim(query: str) -> str:
    """把问句压成陈述核心：「微波炉加热食物会致癌吗」→「微波炉加热食物会致癌」。"""
    core = QUESTION_RE.sub("", query or "").strip(" ，,。.：:、！!")
    return core or (query or "").strip()


def plan(query: str, mode: str) -> list[str]:
    """返回本轮实际要跑的查询列表，最多 3 路。"""
    base = (query or "").strip()
    if not base:
        return []
    core = core_claim(base)
    year = datetime.now().year

    if mode == "claim":
        candidates = [
            base,
            f"{core} 是谣言吗 官方辟谣",
            f"{core} 依据 研究 官方回应",
        ]
    else:
        candidates = [
            base,
            f"{core} 官方 原文 {year}",
            f"{core} 最新进展",
        ]

    out: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        key = re.sub(r"\s+", "", item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out[:3]
