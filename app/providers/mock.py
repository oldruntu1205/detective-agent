"""离线样例检索层。

用途：没有密钥时也能跑通「检索 → 裁决 → 查证卡」全链路，方便本地开发和现场断网兜底。
诚实约束：所有经由此层产出的卡片都会带 notice，前端显示「离线样例」角标，不会被误当成真实查证结果。

样例分两个文件：通用场景（fixtures.json）与领域场景（fixtures.domains.json）。
同领域样例优先命中；当前领域没有对应样例时，退回按关键词匹配，保证通用问句在任意领域都能演示。
"""

from __future__ import annotations

import json
import pathlib

from ..models import SearchHit
from .base import Provider, SearchError

DEMO_DIR = pathlib.Path(__file__).resolve().parents[2] / "demo"
FIXTURE_FILES = ("fixtures.json", "fixtures.domains.json")


class MockProvider(Provider):
    name = "mock"

    def __init__(self, fixture_dir: pathlib.Path | None = None) -> None:
        self.dir = fixture_dir or DEMO_DIR
        self.notice = ""
        self.scenarios: list[dict] = []
        self.last_label = ""
        found = False
        for name in FIXTURE_FILES:
            path = self.dir / name
            if not path.exists():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            self.notice = self.notice or str(data.get("notice") or "离线样例数据")
            self.scenarios.extend(data.get("scenarios") or [])
            found = True
        if not found:
            raise SearchError(f"缺少离线样例文件：{self.dir}")

    def _pick(self, query: str, domain: str) -> dict | None:
        best: dict | None = None
        best_score = 0
        for scenario in self.scenarios:
            score = sum(1 for kw in scenario.get("match", []) if kw in query)
            if score == 0:
                continue
            if domain and scenario.get("domain") == domain:
                score += 3  # 同领域优先，但不排斥通用样例
            if score > best_score:
                best, best_score = scenario, score
        return best

    def search(self, query: str, domain: str = "") -> list[SearchHit]:
        scenario = self._pick(query, domain)
        if not scenario:
            self.last_label = "未内置样例"
            return []
        self.last_label = str(scenario.get("label") or scenario.get("id") or "")

        # route_pages：按查询路线差异化召回，用于演示多路检索「换了问法就能捞到新东西」
        items: list[dict] = list(scenario.get("pages") or [])
        seen_urls = {str(it.get("url") or "") for it in items}
        for cue, extra in (scenario.get("route_pages") or {}).items():
            if cue and cue in query:
                for it in extra or []:
                    url = str(it.get("url") or "")
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    items.append(it)

        hits: list[SearchHit] = []
        for item in items:
            hits.append(SearchHit(
                title=str(item.get("title") or ""),
                url=str(item.get("url") or ""),
                site=str(item.get("site") or ""),
                date=str(item.get("date") or ""),
                passage=str(item.get("passage") or ""),
                content=str(item.get("content") or ""),
                score=float(item.get("score") or 0.0),
                authority_level=item.get("authority_level"),
                favicon=str(item.get("favicon") or ""),
            ))
        return hits

    def labels(self) -> list[dict[str, str]]:
        return [{"id": str(s.get("id")), "label": str(s.get("label")), "domain": str(s.get("domain") or "general"),
                 "query": self._sample_query(s)} for s in self.scenarios]

    @staticmethod
    def _sample_query(scenario: dict) -> str:
        mapping = {
            "microwave": "微波炉加热食物会致癌吗",
            "leftover": "隔夜菜会致癌吗",
            "wsa_quota": "元宝搜索每月免费调用额度是多少次",
            "drama": "那个讲法医的女主剧叫什么",
            "nobel": "2027年诺贝尔文学奖得主是谁",
            "policy_subsidy": "宁波市智能化改造项目最高补贴多少",
            "tender_cert": "这家供应商的 3C 证书还有效吗",
            "health_wrap": "保鲜膜加热会释放致癌物吗",
            "finance_margin": "年报里的毛利率口径含不含运费",
            "labor_probation": "试用期最长可以约定多久",
        }
        return mapping.get(str(scenario.get("id")), str(scenario.get("label") or ""))
