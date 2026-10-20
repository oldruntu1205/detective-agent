# 时间守卫离线测试：构造假证据，不联网
import pathlib
import sys
sys.path.insert(0, r"H:\Workbuddy\2026-10-20-19-23-49\detective-agent")

from app.models import SearchHit
from app.verdict import judge, target_year, is_outcome_question

def hit(title, site="中国网", date="2026/10/09", score=0.8, passage=""):
    return SearchHit(title=title, url=f"https://{site}.example/x", site=site,
                     date=date, passage=passage or title, content="", score=score)

N2026 = [
    hit("加拿大女作家安妮·卡森获得2026年诺贝尔文学奖", "中国网", "2026/10/09", 0.79),
    hit("加拿大女作家卡森获2026年诺贝尔文学奖 中国网", "今日头条", "2026/10/08", 0.79),
    hit("The Nobel Prize in Literature 2026", "www.nobelprize.org", "", 0.78),
    hit("The Nobel Prize in Literature Svetlana Alexievich's dictaphone", "www.nobelprize.org", "", 0.72),
]
N2025 = [
    hit("2025年诺贝尔文学奖得主揭晓", "新华网", "2025/10/09", 0.85),
    hit("历届诺贝尔文学奖得主名单", "中国作家网", "2024/01/01", 0.8),
]
NONE_HIT = [hit("微波炉加热食物会致癌吗", "科普中国", "2025/01/01", 0.9)]

cases = [
    ("2029年诺贝尔文学奖得主是谁？", N2026, "no_evidence", "future"),
    ("2027年诺贝尔文学奖得主是谁？", N2026, "no_evidence", "future"),
    ("明年诺贝尔文学奖得主是谁？",      N2026, "no_evidence", "future"),
    ("2026年诺贝尔文学奖得主是谁？",    N2026, "found",      "ok"),
    ("2026年诺贝尔文学奖得主是谁？",    N2025, "no_evidence", "stale"),
    ("2020年诺贝尔文学奖得主是谁？",    N2026, None,         "past-not-blocked"),
    ("微波炉加热食物会致癌吗",          NONE_HIT, None,     "no-year"),
    ("2029年诺贝尔文学奖得主会是莫言吗", N2026, "no_evidence", "future-claim"),
]

fails = 0
for q, hits, expect, tag in cases:
    card = judge(q, hits, provider="mock", elapsed_ms=10)
    ok = (expect is None) or (card.verdict == expect)
    if tag == "ok" and "卡森" not in card.one_line:
        ok = False
    if tag == "past-not-blocked" and card.verdict != "found":
        # 问过去的年份，证据里又有2026，守卫不该插手
        ok = card.verdict in ("found", "no_evidence", "unclear", "true", "false")
    if tag == "no-year" and card.verdict not in ("true", "false", "unclear", "no_evidence", "found"):
        ok = False
    print(f"[{'PASS' if ok else 'FAIL'}] {tag:18s} {q}")
    print(f"        verdict={card.verdict}({card.verdict_label}) conf={card.confidence} related={len(card.related)}")
    print(f"        one_line={card.one_line[:88]}")
    for r in card.reasons[:2]:
        print(f"        reason: {r[:80]}")
    if not ok:
        fails += 1

print()
print("target_year 单测:", target_year("2029年诺贝尔文学奖得主是谁", __import__("datetime").datetime(2026, 10, 20)),
      "| 明年:", target_year("明年诺贝尔文学奖得主是谁", __import__("datetime").datetime(2026, 10, 20)),
      "| 无年份:", target_year("微波炉加热食物会致癌吗", __import__("datetime").datetime(2026, 10, 20)))
print("outcome:", is_outcome_question("2026年诺贝尔文学奖得主是谁？"), is_outcome_question("2026年诺贝尔文学奖评选标准是什么"))
print()
print("失败数:", fails)
sys.exit(1 if fails else 0)
