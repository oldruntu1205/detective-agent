"""语义判定层：让模型判断「这条结果对用户那句话是什么立场」。

三条硬约束，缺一不可：
1. 只判立场，不判结论。结论永远是裁决层按权重算出来的，模型的话只影响单条证据的标签。
2. 引用必须可校验。模型摘出的原句必须能在该条原文里逐字找到（忽略标点与空白），
   找不到就当这条判定无效，回落到词典法——防止模型顺手编一句「原文」。
3. 单条失败不拖垮整体。任一条解析失败、引用校验不过，只回落那一条。

没有可用模型时整个语义层不启用，直接走词典法（app/stance.py），链路照常跑完。
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request

from .models import SearchHit

ALLOWED = {"support", "refute", "uncertain", "neutral"}
_CJK = re.compile(r"[^\u4e00-\u9fa5A-Za-z0-9]+")
_FENCE = re.compile(r"^```(?:json)?|```$", re.MULTILINE)

SYSTEM_PROMPT = """你是事实核查流程里的立场标注员。

用户要核实的是下面这个问题（下称「该说法」）：
{query}
{domain_context}
我会给你搜索引擎返回的若干条结果。请逐条判断：这条结果对「该说法」持什么立场。

立场只能是以下四种之一：
- support：明确支持该说法成立
- refute：明确否定该说法，或指出它是谣言、不实、没有依据
- uncertain：承认这个问题存在，但表示尚无定论、有争议、证据不足
- neutral：只是背景介绍或相邻话题，没有表态

判定规则：
1. 以正文为准，不要被标题带偏。标题在转述传言、正文却在辟谣的，判 refute。
2. quote 必须从该条原文里逐字摘抄一句最能代表立场的话。不许改写、不许拼接、不许用自己的话概括。
3. 摘不出合适的原句，就判 neutral，quote 留空。
4. 不要判断该说法本身是对是错，那不是你的工作。

只输出 JSON，不要任何解释文字：
{{"items":[{{"i":1,"stance":"refute","quote":"原文里的一句","reason":"20字以内的理由"}}]}}"""


def _normalize(text: str) -> str:
    return _CJK.sub("", text or "")


def quote_verified(quote: str, source: str) -> bool:
    """原句必须能在原文里逐字找到（忽略标点空白），否则视为模型编造。"""
    q = _normalize(quote)
    if len(q) < 8:
        return False
    return q in _normalize(source)


class SemanticJudge:
    """批量语义判定。一次请求判完所有结果，省调用也省时间。"""

    name = "semantic"

    def __init__(self, base_url: str, api_key: str, model: str, timeout: int = 25,
                 domain_context: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.domain_context = domain_context
        self._cache: dict[str, dict] = {}

    # ---------- 缓存 ----------
    def _key(self, query: str, hit: SearchHit) -> str:
        """领域上下文进缓存键，避免同一句话在不同领域间复用错误结论。"""
        raw = f"{self.domain_context}|{query}|{hit.url}|{hit.text}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    # ---------- 组装请求 ----------
    @staticmethod
    def _user_message(query: str, hits: list[SearchHit]) -> str:
        lines = [f"待核实的说法：{query}", "", "以下是检索结果：", ""]
        for idx, hit in enumerate(hits, 1):
            body = (hit.passage or hit.content or "").strip()
            lines.append(f"[{idx}] 标题：{hit.title}")
            lines.append(f"来源：{hit.display_site} ｜ 时间：{hit.date or '未标注'}")
            lines.append(f"正文：{body[:600]}")
            lines.append("")
        return "\n".join(lines)

    def _call(self, query: str, hits: list[SearchHit]) -> str:
        context = f"\n本领域判定口径（务必遵守）：{self.domain_context}\n" if self.domain_context else "\n"
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT.format(query=query, domain_context=context)},
                {"role": "user", "content": self._user_message(query, hits)},
            ],
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        return str(data["choices"][0]["message"]["content"])

    # ---------- 主流程 ----------
    def classify(self, query: str, hits: list[SearchHit]) -> tuple[dict[int, dict], str]:
        """返回 ({hit_index: {stance, quote, reason}}, note)。

        hit_index 与传入 hits 的位置一一对应；未被返回的下标由调用方回落到词典法。
        """
        if not hits:
            return {}, ""
        results: dict[int, dict] = {}
        pending: list[tuple[int, SearchHit]] = []

        for idx, hit in enumerate(hits):
            cached = self._cache.get(self._key(query, hit))
            if cached:
                results[idx] = cached
            else:
                pending.append((idx, hit))

        note = ""
        if not pending:
            return results, "全部命中缓存"
        cached_count = len(results)

        try:
            content = _FENCE.sub("", self._call(query, [h for _, h in pending])).strip()
            parsed = json.loads(content)
            items = parsed.get("items") if isinstance(parsed, dict) else parsed
            if not isinstance(items, list):
                raise ValueError("items 不是数组")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:160]
            return results, f"语义判定不可用（HTTP {exc.code}：{detail}），已回落词典法"
        except urllib.error.URLError as exc:
            return results, f"语义判定不可用（{exc.reason}），已回落词典法"
        except Exception as exc:  # noqa: BLE001 - 解析失败一律回落，不中断核查
            return results, f"语义判定返回不可解析（{type(exc).__name__}），已回落词典法"

        rejected = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                pos = int(item.get("i")) - 1
            except (TypeError, ValueError):
                continue
            if not (0 <= pos < len(pending)):
                continue
            idx, hit = pending[pos]
            stance = str(item.get("stance") or "").strip().lower()
            if stance not in ALLOWED:
                rejected += 1
                continue
            quote = str(item.get("quote") or "").strip()
            if stance != "neutral" and not quote_verified(quote, hit.text):
                # 引用对不上原文：这条判定作废，交回词典法
                rejected += 1
                continue
            payload = {
                "stance": stance,
                "quote": quote[:180] if quote else (hit.title or "")[:120],
                "reason": str(item.get("reason") or "").strip()[:40],
            }
            results[idx] = payload
            self._cache[self._key(query, hit)] = payload

        filled = len(results) - cached_count
        missing = len(pending) - filled - rejected
        parts = [f"语义判定 {len(results)} 条"]
        if rejected:
            parts.append(f"{rejected} 条因引用不可校验或格式异常回落词典法")
        if missing > 0:
            parts.append(f"{missing} 条未被模型覆盖，由词典法补齐")
        return results, "，".join(parts)
