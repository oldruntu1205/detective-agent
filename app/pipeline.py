"""把三层串起来：领域包 → 检索 → 裁决 → 表达。"""

from __future__ import annotations

import time

from . import llm
from .config import config
from .domain import Domain, list_domains, load as load_domain
from .models import Card, VERDICT_LABEL
from .providers import MockProvider, SearchError, TencentWsaProvider
from .semantic import SemanticJudge
from .verdict import detect_mode, judge
from .version import __version__


def make_provider(override: str = "") -> object:
    which = (override or config.resolved_provider).lower()
    if which == "wsa":
        return TencentWsaProvider(
            config.secret_id, config.secret_key,
            region=config.region, mode=config.mode, cnt=config.cnt,
            freshness=config.freshness, industry=config.industry,
        )
    return MockProvider()


def make_semantic_judge(domain: Domain | None = None) -> SemanticJudge | None:
    """语义判定层：只有配置了模型且引擎选择为 semantic 时才启用，否则返回 None 走词典法。"""
    if config.resolved_stance_engine != "semantic" or not config.has_llm:
        return None
    return SemanticJudge(
        config.llm_base_url, config.llm_api_key, config.llm_model, config.llm_timeout,
        domain_context=getattr(domain, "semantic_context", "") if domain else "",
    )


def _norm_url(url: str) -> str:
    u = (url or "").strip().lower()
    u = u.split("#")[0]
    for prefix in ("https://", "http://"):
        if u.startswith(prefix):
            u = u[len(prefix):]
    if u.startswith("www."):
        u = u[4:]
    return u.rstrip("/")


def search_multi(provider: object, query: str, domain_id: str) -> tuple[list, dict]:
    """跑多路查询并合并去重。返回 (hits, 查询记录)。"""
    from .query_plan import plan
    from .verdict import detect_mode

    queries = plan(query, detect_mode(query))
    merged: dict[str, object] = {}
    trace: list[dict] = []
    fetched = 0
    merged_hits = 0
    matched = ""

    for idx, q in enumerate(queries):
        try:
            got = provider.search(q, domain_id)  # type: ignore[attr-defined]
        except SearchError as exc:
            trace.append({"query": q, "hits": 0, "new": 0, "error": str(exc)})
            if idx == 0:
                raise
            continue
        fetched += len(got)
        new = 0
        for hit in got:
            key = _norm_url(hit.url)
            exists = merged.get(key)
            if exists is None:
                hit.via = q
                merged[key] = hit
                new += 1
            else:
                if hit.score > exists.score:  # type: ignore[attr-defined]
                    exists.score = hit.score  # type: ignore[attr-defined]
        merged_hits += new
        label = str(getattr(provider, "last_label", "") or "")
        if label and label != "未内置样例" and not matched:
            matched = label
        trace.append({"query": q, "hits": len(got), "new": new})

    return list(merged.values()), {
        "queries": queries,
        "trace": trace,
        "fetched": fetched,
        "unique": merged_hits,
        "label": matched,
    }


def check(query: str, provider_override: str = "", domain_id: str = "general") -> dict:
    query = (query or "").strip()
    if not query:
        raise ValueError("query 不能为空")

    domain = load_domain(domain_id)
    started = time.perf_counter()
    provider_name = (provider_override or config.resolved_provider).lower() or "mock"

    try:
        provider = make_provider(provider_override)
        provider_name = getattr(provider, "name", provider_name)
        hits, plan_info = search_multi(provider, query, domain.id)
    except SearchError as exc:
        card = Card(
            query=query,
            mode=detect_mode(query),
            verdict="error",
            verdict_label=domain.label("error", VERDICT_LABEL["error"]),
            confidence=0.0,
            one_line="检索层没有正常返回，这次不给结论。",
            reasons=[str(exc), "按本工具规则：查不到就说查不到，不用模型记忆里的东西补答案。"],
            query_time=time.strftime("%Y-%m-%d %H:%M:%S"),
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            provider=provider_name,
            notice="检索失败",
            stats={"error": True},
            domain=domain.to_dict(),
            audit_steps=[
                "先检查 .env 里的 TENCENTCLOUD_SECRET_ID / SECRET_KEY 是否填写，以及元宝搜索服务是否已开通。",
                "临时要验证链路可以加 --provider mock，但那张卡会标明「离线样例」，不能当真实结论使用。",
                "本条没有给出结论，不存在被推翻的结论；检索层恢复后重跑同一句即可。",
            ],
            version=__version__,
        )
        return card.to_dict()

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    notice = ""
    if provider_name == "mock":
        notice = getattr(provider, "notice", "离线样例数据")
        if plan_info.get("label"):
            notice += f"｜当前样例：{plan_info['label']}"

    card = judge(query, hits, provider=provider_name, elapsed_ms=elapsed_ms,
                 notice=notice, semantic_judge=make_semantic_judge(domain), domain=domain)
    card.version = __version__
    card.stats["plan"] = plan_info
    engine = card.stats.get("engine") or {}
    if engine.get("note") and "回落" in str(engine.get("note")):
        card.notice = (card.notice + "｜" if card.notice else "") + str(engine["note"])
    llm.refine(card)
    return card.to_dict()


def samples(domain_id: str = "general") -> list[dict]:
    """示例问句跟着领域走：换行业就换示例，前端无需改代码。"""
    domain = load_domain(domain_id)
    return [{"id": f"{domain.id}-{i}", "label": q, "query": q} for i, q in enumerate(domain.queries)]


def domains() -> list[dict]:
    return list_domains()
