"""检索层与裁决层之外的第三块：表达层（可选）。

边界写死：模型只做「一句话结论」和「冲突解释」的文字润色，绝不参与标签判定。
原因很直接——标签必须可复现、可审计，同一批证据换一台机器、换一次调用都得给出同一结论。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from .config import config
from .models import Card

SYSTEM_PROMPT = """你是一个事实核查结果的文字编辑。你会收到一份已经由规则引擎判定完成的核查结果，
你的任务只有两个：
1. 用一句话（不超过 60 字）复述这个结论，语气克制，不夸张。
2. 如果有冲突来源，用一句话说清冲突在哪。

硬性要求：
- 不得改变已经给出的结论标签（真 / 假 / 说不准 / 没查到可靠来源）。
- 不得引入输入里没有的事实、数字、机构名。
- 不得使用「据专家称」「业内普遍认为」这类无出处的表述。
- 只输出 JSON：{"one_line": "...", "conflict_note": "..."}，没有冲突时 conflict_note 为空字符串。"""


def refine(card: Card) -> None:
    if not config.has_llm:
        return
    payload = {
        "model": config.llm_model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps({
                "query": card.query,
                "verdict_label": card.verdict_label,
                "rule_reason": card.reasons[:3],
                "support_sites": [e.hit.display_site for e in card.evidence if e.stance == "support"][:3],
                "refute_sites": [e.hit.display_site for e in card.evidence if e.stance == "refute"][:3],
            }, ensure_ascii=False)},
        ],
    }
    request = urllib.request.Request(
        f"{config.llm_base_url}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.llm_api_key}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        content = data["choices"][0]["message"]["content"].strip()
        content = content.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(content)
    except Exception:  # noqa: BLE001 - 表达层失败不影响结论，静默降级
        return

    one_line = str(parsed.get("one_line") or "").strip()
    if one_line and len(one_line) <= 120:
        card.one_line = one_line
        card.stats["polished"] = True
    note = str(parsed.get("conflict_note") or "").strip()
    if note and card.conflicts:
        card.conflicts.append({"side": "冲突说明（模型生成）", "weight": 0,
                               "items": [{"title": note, "url": "", "site": "", "date": "",
                                          "quote": "", "stance": "neutral",
                                          "stance_label": "文字说明", "tier": 0,
                                          "tier_label": "", "domain": "", "score": 0, "weight": 0}]})
