"""本地联调用的 OpenAI 兼容桩（不是产品代码，不要拿它参赛）。

作用：没有真实模型密钥时，仍能把「语义判定层」这条路径跑通，验证三件事：
  1. 批量请求与 JSON 解析能对上号
  2. 引用逐字校验会拦下编造的原文（第 3 条故意返回假引用）
  3. 单条失败时只有那一条回落到词典法，其余照常走语义判定

用法：
    python scripts/mock_llm.py                     # 监听 127.0.0.1:8799
    # 另一个终端：
    LLM_BASE_URL=http://127.0.0.1:8799/v1 LLM_API_KEY=stub LLM_MODEL=stub \
    STANCE_ENGINE=semantic python run.py "微波炉加热食物会致癌吗"
"""

from __future__ import annotations

import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.stance import claim_terms, detect_stance  # noqa: E402
from app.domain import list_domains, load as load_domain  # noqa: E402

BLOCK = re.compile(r"^\[(\d+)\] 标题：(.*)$")
CLAIM_LINE = re.compile(r"^待核实的说法：(.*)$", re.MULTILINE)
FABRICATED = "这句话是桩服务故意编的，原文里并不存在，用来测试引用校验。"
DOMAINS = list_domains()


def guess_domain(system_msg: str):
    """从系统提示里的「本领域判定口径」反查领域包，让桩也能用上行业线索词。"""
    if "本领域判定口径" not in system_msg:
        return None
    for item in DOMAINS:
        domain = load_domain(item["id"])
        snippet = (domain.semantic_context or "")[:18]
        if snippet and snippet in system_msg:
            return domain
    return None


def parse_hits(message: str) -> list[dict]:
    items: list[dict] = []
    current: dict | None = None
    for line in (message or "").splitlines():
        matched = BLOCK.match(line.strip())
        if matched:
            if current:
                items.append(current)
            current = {"i": int(matched.group(1)), "title": matched.group(2), "body": ""}
            continue
        if current is None:
            continue
        if line.startswith("正文："):
            current["body"] = line[len("正文："):]
    if current:
        items.append(current)
    return items


STANCE_CN = {"support": "支持该说法", "refute": "否定该说法",
             "uncertain": "尚无定论", "neutral": "仅陈述背景"}


def build_reply(message: str, domain=None) -> str:
    hits = parse_hits(message)
    matched = CLAIM_LINE.search(message or "")
    terms = claim_terms(matched.group(1)) if matched else []
    refute_add = getattr(domain, "refute_cues", None) if domain else None
    support_add = getattr(domain, "support_cues", None) if domain else None
    out = []
    for hit in hits:
        result = detect_stance(f"{hit['title']}。{hit['body']}", terms, refute_add, support_add)
        stance = str(result["stance"])
        quote = str(result["quote"])
        if stance != "neutral" and len(quote) < 10:
            stance, quote = "neutral", ""   # 摘不出像样原句就判 neutral，和真模型的要求一致
        if hit["i"] == 3:
            quote = FABRICATED  # 故意编造，检验校验环节
        out.append({
            "i": hit["i"],
            "stance": stance,
            "quote": quote,
            "reason": f"桩服务判定：{STANCE_CN.get(stance, stance)}",
        })
    return json.dumps({"items": out}, ensure_ascii=False)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        print(f"[stub] {fmt % args}")

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        messages = body.get("messages") or []
        user_msg = next((m.get("content") for m in messages if m.get("role") == "user"), "")
        system_msg = next((m.get("content") for m in messages if m.get("role") == "system"), "")

        if "立场标注员" in system_msg:
            content = build_reply(user_msg, guess_domain(system_msg))
        else:
            content = json.dumps({"one_line": "", "conflict_note": ""}, ensure_ascii=False)

        payload = {"choices": [{"message": {"role": "assistant", "content": content}}]}
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8799
    print(f"OpenAI 兼容桩已启动：http://127.0.0.1:{port}/v1  （第 3 条会故意返回假引用）")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
