#!/usr/bin/env python
"""入口。

  python run.py                                 启动网页
  python run.py "微波炉加热食物会致癌吗"          命令行查证
  python run.py "隔夜菜会致癌吗" --json out.json  命令行查证并存 JSON
  python run.py --provider wsa                  强制走真实元宝搜索
"""

from __future__ import annotations

import argparse
import json
import sys

from app.config import config
from app.version import VERSION_HISTORY, __version__

COLOR = {"true": "\033[32m", "false": "\033[31m", "unclear": "\033[33m",
         "no_evidence": "\033[90m", "found": "\033[36m", "error": "\033[31m"}
RESET = "\033[0m"
BOLD = "\033[1m"


def _c(text: str, verdict: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"{COLOR.get(verdict, '')}{text}{RESET}"


def print_card(card: dict) -> None:
    stats = card.get("stats") or {}
    engine = stats.get("engine") or {}
    domain_name = (card.get("domain") or {}).get("name") or "通用查证"
    print()
    print(f"{BOLD}问：{card['query']}{RESET}")
    print(f"领域：{domain_name} ｜ 检索层：{card['provider']} ｜ 模式：{'查真假' if card['mode'] == 'claim' else '查最新 / 查模糊'}"
          f" ｜ 判定：{'语义' if engine.get('name') == 'semantic' else '词典'}"
          f"（语义 {engine.get('semantic', 0)} / 词典 {engine.get('lexicon', 0)}）"
          f" ｜ 耗时 {card['elapsed_ms']}ms ｜ {card['query_time']}"
          f" ｜ v{card.get('version') or '—'}")
    if card.get("notice"):
        print(f"提示：{card['notice']}")
    print("-" * 70)
    print(f"结论：{_c(card['verdict_label'], card['verdict'])}"
          + (f"　置信度 {card['confidence']:.0%}" if card["confidence"] else "　（证据不足以给置信度）"))
    print(f"一句话：{card['one_line']}")
    print()
    print("裁决依据：")
    for i, reason in enumerate(card["reasons"], 1):
        print(f"  {i}. {reason}")

    if card["key_facts"]:
        print()
        print("要点：")
        for item in card["key_facts"]:
            print(f"  · {item['text']}")
            print(f"    —— {item['site']}（{item['tier_label']}）{item['url']}")

    if card["conflicts"]:
        print()
        print("来源冲突：")
        for side in card["conflicts"]:
            print(f"  [{side['side']}] 权重 {side.get('weight', 0)}")
            for item in side["items"]:
                print(f"    - {item['site']}｜{item['title']}")
                if item.get("quote"):
                    print(f"      「{item['quote']}」")
                if item.get("url"):
                    print(f"      {item['url']}")

    cond = card.get("condition_diff") or {}
    if cond.get("differ"):
        print()
        print(f"条件差异（{cond.get('side_a', 'A')} ↔ {cond.get('side_b', 'B')}）：")
        if cond.get("a_only"):
            print(f"  仅 {cond.get('side_a', 'A')} 一方限定在：{'、'.join(cond['a_only'])}")
        if cond.get("b_only"):
            print(f"  仅 {cond.get('side_b', 'B')} 一方限定在：{'、'.join(cond['b_only'])}")
        if cond.get("shared"):
            print(f"  双方共同限定：{'、'.join(cond['shared'])}")
        print("  → 这两句回答的可能不是同一个问题，先确认你关心的是哪种情形。")

    if card["numbers"]:
        print()
        print("关键数字核对（仅提示，不参与裁决）：")
        for group in card["numbers"]:
            print(f"  [{group['label']}] {group['note']}")
            for value in group["values"]:
                print(f"    {value['shown']:>10}　{value['site']}　{value['ctx'][:46]}")

    plan = stats.get("plan") or {}
    if plan.get("trace"):
        print()
        print("检索路线：")
        for i, t in enumerate(plan.get("trace") or [], 1):
            if t.get("error"):
                print(f"  {i}. {t['query']}　→ 失败：{t['error']}")
            else:
                print(f"  {i}. {t['query']}　→ 捞回 {t['hits']} 条，新增 {t['new']} 条")
        if plan.get("fetched"):
            print(f"  合计抓取 {plan['fetched']} 条，去重后 {plan.get('unique', 0)} 条")

    print()
    print("来源证据：")
    for ev in card["evidence"]:
        mark = {"support": "＋", "refute": "－", "uncertain": "？", "neutral": "·"}[ev["stance"]]
        by = "语义" if ev.get("stance_by") == "semantic" else "词典"
        synd = "　[转载]" if ev.get("is_syndicated") else ""
        print(f"  {mark} [{ev['tier_label']}] {ev['site']}　{ev['date']}　相关性 {ev['score']:.2f}　权重 {ev['weight']}　[{by}]{synd}")
        print(f"    {ev['title']}")
        print(f"    「{ev['quote']}」")
        if ev.get("stance_reason"):
            print(f"    （{by}判定理由：{ev['stance_reason']}）")
        if ev.get("is_syndicated") and ev.get("syndicated_site"):
            print(f"    （转载自《{ev['syndicated_site']}》，不计独立印证，权重已减半）")
        print(f"    {ev['url']}")
    print()
    print(f"原始 {stats.get('raw', 0)} 条 → 采信 {stats.get('used', 0)} 条 → "
          f"可判定 {stats.get('judged', 0)} 条 → 丢弃 {stats.get('dropped', 0)} 条（低相关/同站点超限）"
          f"　｜ 独立源 {stats.get('independent_sources', 0)} 个，转载 {stats.get('syndicated', 0)} 条")
    if engine.get("note"):
        print(f"判定引擎：{engine['note']}")

    if card.get("audit_steps"):
        print()
        print("想推翻这张卡，可以这样试：")
        for i, step in enumerate(card["audit_steps"], 1):
            print(f"  {i}. {step}")

    if card.get("gaps"):
        print()
        print("再补这几样，这件事就能进一步定性：")
        for i, gap in enumerate(card["gaps"], 1):
            print(f"  {i}. {gap}")
    print()


def main() -> None:
    ap = argparse.ArgumentParser(description="AI元宝大侦探 —— 查得到，信得过 · 侦探赛道查证 Agent")
    ap.add_argument("query", nargs="*", help="要核查的问题；留空则启动网页")
    ap.add_argument("--provider", default="", choices=["", "wsa", "mock"], help="强制指定检索层")
    ap.add_argument("--domain", default="general",
                    choices=["general", "policy", "tender", "health", "finance", "labor"],
                    help="领域包：换权威源、判定口径与结论用语")
    ap.add_argument("--port", type=int, default=None, help="网页端口")
    ap.add_argument("--host", default=None)
    ap.add_argument("--json", dest="json_path", default="", help="把结果写入 JSON 文件")
    ap.add_argument("--share", action="store_true", help="同时生成自包含静态查证卡（out/cards/）")
    ap.add_argument("--out-dir", default="", help="静态卡输出目录，默认 out/cards")
    ap.add_argument("--open", action="store_true", help="启动网页后自动打开浏览器")
    ap.add_argument("--version", action="store_true", help="只看版本号和版本历史")
    args = ap.parse_args()

    if args.version:
        print(f"AI元宝大侦探 · 查得到，信得过  v{__version__}")
        print()
        for item in VERSION_HISTORY:
            print(f"  v{item['version']}  {item['title']}")
            print(f"          {item['detail']}")
        return

    if args.query:
        from app.pipeline import check
        card = check(" ".join(args.query), args.provider, args.domain)
        print_card(card)
        if args.json_path:
            import os
            os.makedirs(os.path.dirname(args.json_path) or ".", exist_ok=True)
            with open(args.json_path, "w", encoding="utf-8") as fh:
                json.dump(card, fh, ensure_ascii=False, indent=2)
            print(f"已写入 {args.json_path}")
        if args.share:
            from app.share import save_static
            path = save_static(card, args.out_dir or None)
            print(f"静态查证卡：{path}")
            print(f"同目录另有原始 JSON：{path.with_suffix('.json')}")
        return

    if args.host:
        config.host = args.host
    if args.port:
        config.port = args.port
    if args.open:
        import threading
        import webbrowser
        url = f"http://{config.host}:{config.port}/"
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    from app.server import serve
    serve()


if __name__ == "__main__":
    main()
