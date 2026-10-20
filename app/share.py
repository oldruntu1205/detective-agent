"""静态查证卡：把一次查证结果渲染成自包含 HTML 文件。

自包含的意思是：不引用任何外部 CSS / JS / 字体 / 图片，双击就能看，断网也能看，
可以直接丢进仓库、发给别人、或者当参赛附件提交。所有来源链接都保留可点。

卡里嵌了一份原始 JSON，方便机器人或后续工具解析，人看图和机器读数据互不干扰。
"""

from __future__ import annotations

import hashlib
import html
import json
import pathlib
from datetime import datetime

from .config import ROOT
from .models import Card

DEFAULT_DIR = ROOT / "out" / "cards"

VERDICT_COLOR = {
    "true": ("#10854f", "#e9f7ef"),
    "false": ("#c8342f", "#fdeceb"),
    "unclear": ("#a86a00", "#fdf3e0"),
    "found": ("#1f5fa8", "#eaf2fb"),
    "no_evidence": ("#6b7280", "#eef0f3"),
    "error": ("#c8342f", "#fdeceb"),
}
MARK = {"support": "＋", "refute": "－", "uncertain": "？", "neutral": "·"}
MARK_COLOR = {"support": "#10854f", "refute": "#c8342f", "uncertain": "#a86a00", "neutral": "#8a909c"}
MODE_TEXT = {"claim": "查真假", "open": "查最新 / 查模糊"}


def fingerprint(card: dict) -> str:
    """对「问句 + 结论 + 证据来源 + 规则版本」做指纹，用来标识这张卡的唯一性。

    版本进指纹是有意的：同一句问话在 v1.3 和 v1.4 下即使结论相同，也是两张不同的卡，
    因为产出它的规则不一样。指纹要让这两张卡区分得开。
    """
    basis = {
        "q": card.get("query"),
        "v": card.get("verdict"),
        "e": [(e.get("url"), e.get("stance"), e.get("weight")) for e in card.get("evidence", [])],
        "t": card.get("query_time"),
        "ver": card.get("version"),
    }
    raw = json.dumps(basis, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _e(value: object) -> str:
    return html.escape(str(value if value is not None else ""))


def render_html(card: dict) -> str:
    fp = fingerprint(card)
    verdict = str(card.get("verdict") or "no_evidence")
    fg, bg = VERDICT_COLOR.get(verdict, VERDICT_COLOR["no_evidence"])
    stats = card.get("stats") or {}
    engine = stats.get("engine") or {}
    provider_text = "元宝搜索 · 实时检索" if card.get("provider") == "wsa" else "离线样例数据"
    engine_text = "语义判定" if engine.get("name") == "semantic" else "词典兜底"
    engine_detail = f"语义 {engine.get('semantic', 0)} 条 / 词典 {engine.get('lexicon', 0)} 条"
    conf = float(card.get("confidence") or 0)
    conf_pct = round(conf * 100)

    conf_block = ""
    if conf > 0:
        conf_block = f"""
        <div class="conf"><span>置信度</span>
          <div class="bar"><i style="width:{conf_pct}%"></i></div>
          <b>{conf_pct}%</b></div>"""

    facts_html = ""
    if card.get("key_facts"):
        items = "".join(
            f"""<li><div class="t">{_e(f.get('text'))}</div>
            <div class="s">{_e(f.get('site'))}（{_e(f.get('tier_label'))}）· {_e(f.get('date') or '未标注时间')} ·
            <a href="{_e(f.get('url'))}" target="_blank" rel="noopener">原文</a></div></li>"""
            for f in card["key_facts"]
        )
        facts_html = f'<section><h2>要点</h2><ul class="facts">{items}</ul></section>'

    # 相近内容：没查到可靠来源时列出来当参考，明说了「不是答案」
    related_html = ""
    rel = card.get("related") or []
    if rel:
        items = "".join(
            f"""<li><div class="t">{_e(r.get('text') or r.get('title'))}</div>
            <div class="s">{_e(r.get('site'))}（{_e(r.get('tier_label'))}）· {_e(r.get('date') or '未标注时间')} ·
            <a href="{_e(r.get('url'))}" target="_blank" rel="noopener">原文</a></div></li>"""
            for r in rel
        )
        related_html = (
            '<section><h2>相近内容（不是答案，仅供参考）</h2>'
            '<p class="hint">这些检索结果回答的是别的问题，不是上面这个提问的答案。'
            '不参与裁决，列出来供参考。</p>'
            f'<ul class="facts related">{items}</ul></section>'
        )

    conflict_html = ""
    # 条件差异：两方吵的其实不是同一件事（要先于 conflict_html 生成）
    cond = card.get("condition_diff") or {}
    cond_html = ""
    if cond.get("differ"):
        def chips(words: list) -> str:
            if not words:
                return '<span class="cnone">无额外限定</span>'
            return "".join(f'<span class="cchip">{_e(w)}</span>' for w in words)

        shared_row = ""
        if cond.get("shared"):
            shared_row = (f'<div class="crow"><span class="cside">双方共同限定</span>'
                          f'{chips(cond["shared"])}</div>')
        cond_html = f"""
        <div class="conddiff">
          <div class="ctitle">两方讨论的条件并不相同</div>
          <div class="crow"><span class="cside">{_e(cond.get('side_a') or '一方')}</span>{chips(cond.get('a_only'))}</div>
          <div class="crow"><span class="cside">{_e(cond.get('side_b') or '另一方')}</span>{chips(cond.get('b_only'))}</div>
          {shared_row}
          <div class="cnote">这更像两个不同条件下的两个结论，不宜按同一句话裁决——先确认你关心的是哪一种情形。</div>
        </div>"""

    if card.get("conflicts"):
        blocks = []
        for side in card["conflicts"]:
            items = "".join(
                f"""<div class="citem"><div class="site">{_e(it.get('site') or '模型说明')}</div>
                {f'<div class="quote">「{_e(it.get("quote"))}」</div>' if it.get('quote') else ''}
                {f'<a href="{_e(it.get("url"))}" target="_blank" rel="noopener">{_e(it.get("url"))}</a>' if it.get('url') else ''}
                </div>"""
                for it in side.get("items", [])
            )
            blocks.append(
                f"""<div class="cside"><header><span>{_e(side.get('side'))}</span>
                <span>权重 {_e(side.get('weight', 0))}</span></header>{items}</div>"""
            )
        conflict_html = (
            '<section><h2>来源冲突</h2>'
            '<p class="hint">两方都够权威时并排列出，不替你站队。</p>'
            f'<div class="cgrid">{"".join(blocks)}</div>{cond_html}</section>'
        )

    reasons_html = "".join(f"<li>{_e(r)}</li>" for r in card.get("reasons") or [])

    # 关键数字核对（不参与裁决）
    num_html = ""
    if card.get("numbers"):
        blocks = []
        for g in card["numbers"]:
            rows = "".join(
                f"""<div class="numrow"><span class="numval">{_e(v.get('shown'))}</span>
                <span class="numsite">{_e(v.get('site'))}</span>
                <span class="numctx">{_e(v.get('ctx'))}</span>
                {f'<a href="{_e(v.get("url"))}" target="_blank" rel="noopener">原文</a>' if v.get('url') else ''}</div>"""
                for v in g.get("values", [])
            )
            blocks.append(f"""<div class="numgroup">
              <div class="numhead"><span class="numtag">{_e(g.get('label'))}</span>
              <span class="numnote">{_e(g.get('note'))}</span></div>{rows}</div>""")
        num_html = (
            '<section><h2>关键数字核对</h2>'
            '<p class="hint">同一量纲在不同来源里对不上时列在这里。只做提示，不参与裁决。</p>'
            f'{"".join(blocks)}</section>'
        )

    # 最小补证清单
    gaps_html = ""
    if card.get("gaps"):
        items = "".join(f"<li>{_e(g)}</li>" for g in card["gaps"])
        gaps_html = (
            '<section><h2>再补这几样，就能进一步定性</h2>'
            '<p class="hint">「没查到」不是终点。下面是这张卡实际缺的东西，一条一条都能去补。</p>'
            f'<ol class="gaps">{items}</ol></section>'
        )

    # 检索路线：一次查证跑了哪几路问法，每路捞回多少、新增多少
    plan = stats.get("plan") or {}
    trace = plan.get("trace") or []
    plan_html = ""
    if trace:
        items = "".join(
            f"""<li><div class="pq">{_e(t.get('query'))}</div>
            <div class="pm">{_e(t.get('error')) if t.get('error')
                else f"捞回 {t.get('hits', 0)} 条 · 新增 {t.get('new', 0)} 条"}</div></li>"""
            for t in trace
        )
        plan_html = (
            f'<section><h2>检索路线（{len(trace)} 路 · 去重后 {_e(plan.get("unique", 0))} 条）</h2>'
            '<p class="hint">同一句话换几路问法去查，专门捞反方与官方口径，避免只看到同温层证据。</p>'
            f'<ol class="plan">{items}</ol></section>'
        )

    # 推翻路径
    audit_html = ""
    if card.get("audit_steps"):
        items = "".join(f"<li>{_e(a)}</li>" for a in card["audit_steps"])
        audit_html = (
            '<section><h2>想推翻这张卡，可以这样试</h2>'
            '<p class="hint">可信度不靠承诺，靠可复核。前面几条是最容易被推翻的地方，最后一条是留一检验的实测结果。</p>'
            f'<ol class="audit">{items}</ol></section>'
        )

    ev_html = ""
    for ev in card.get("evidence") or []:
        stance = str(ev.get("stance") or "neutral")
        by_text = "语义" if ev.get("stance_by") == "semantic" else "词典"
        reason = ev.get("stance_reason") or ""
        synd = bool(ev.get("is_syndicated"))
        synd_tag = '<span class="syndtag">转载</span>' if synd else ""
        synd_note = (
            f'<div class="syndnote">原文出自《{_e(ev.get("syndicated_site"))}》，本条为转载，不计独立印证，权重已减半</div>'
            if synd and ev.get("syndicated_site") else ""
        )
        ev_html += f"""
        <div class="ev{' ev-synd' if synd else ''}">
          <div class="ev-head">
            <span class="mark" style="color:{MARK_COLOR.get(stance, '#8a909c')}">{MARK.get(stance, '·')}</span>
            <span class="tier">T{_e(ev.get('tier'))} {_e(str(ev.get('tier_label') or '').replace('T' + str(ev.get('tier')), '').strip())}</span>
            {synd_tag}
            <a class="title" href="{_e(ev.get('url'))}" target="_blank" rel="noopener">{_e(ev.get('title') or ev.get('url'))}</a>
          </div>
          <div class="quote">「{_e(ev.get('quote'))}」</div>
          {f'<div class="sreason">{by_text}判定理由：{_e(reason)}</div>' if reason else ''}
          {synd_note}
          <div class="ev-foot">
            <span>{_e(ev.get('site'))}</span>
            <span>{_e(ev.get('date') or '未标注时间')}</span>
            <span>{_e(ev.get('stance_label'))}</span>
            <span>相关性 {_e(ev.get('score'))}</span>
            <span>权重 {_e(ev.get('weight'))}</span>
            <span class="by">{by_text}</span>
          </div>
        </div>"""

    notice_html = f'<div class="notice">{_e(card.get("notice"))}</div>' if card.get("notice") else ""
    domain_info = card.get("domain") or {}
    domain_name = str(domain_info.get("name") or "通用查证")
    disclaimer = str(domain_info.get("disclaimer") or "")
    disclaimer_html = f'<div class="disc">{_e(disclaimer)}</div>' if disclaimer else ""
    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    raw_json = json.dumps(card, ensure_ascii=False, indent=2).replace("</", "<\\/")

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>查证卡 · {_e(card.get('query'))} · AI元宝大侦探</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;padding:32px 20px 56px;background:#f6f7f9;color:#16181d;
font:15px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
-webkit-font-smoothing:antialiased}}
.wrap{{max-width:900px;margin:0 auto}}
.brand{{display:flex;align-items:baseline;justify-content:space-between;gap:16px;
margin-bottom:16px;color:#5b6270;font-size:13px}}
.brand b{{font-size:15px;color:#16181d}}
.card{{background:#fff;border:1px solid #e4e7ec;border-left:5px solid {fg};border-radius:12px;
padding:22px 24px;box-shadow:0 1px 2px rgba(16,24,40,.05),0 8px 24px rgba(16,24,40,.04)}}
.q{{font-size:13px;color:#8a909c;margin-bottom:4px}}
.verdict{{font-size:32px;font-weight:700;color:{fg};letter-spacing:.5px;line-height:1.25}}
.line{{margin:12px 0 0;font-size:16px}}
.conf{{display:flex;align-items:center;gap:10px;margin-top:16px;font-size:12px;color:#8a909c}}
.bar{{flex:1;max-width:300px;height:6px;background:#eef0f3;border-radius:99px;overflow:hidden}}
.bar i{{display:block;height:100%;background:#2f5bea}}
.conf b{{color:#5b6270;font-variant-numeric:tabular-nums}}
.meta{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px 18px;
margin-top:18px;padding-top:16px;border-top:1px dashed #e4e7ec;font-size:12px;color:#5b6270}}
.meta div span{{display:block;color:#8a909c;margin-bottom:2px}}
.notice{{margin:0 0 14px;padding:9px 13px;border-radius:9px;background:#fdf3e0;border:1px solid #f0dcb4;
color:#7a4f00;font-size:12.5px}}
section{{background:#fff;border:1px solid #e4e7ec;border-radius:12px;padding:18px 22px;margin-top:14px;
box-shadow:0 1px 2px rgba(16,24,40,.04)}}
h2{{margin:0 0 12px;font-size:13px;color:#5b6270;letter-spacing:.6px}}
.hint{{margin:-6px 0 12px;font-size:12px;color:#8a909c}}
ol{{margin:0;padding-left:20px}} ol li{{margin-bottom:8px}} ol li:last-child{{margin-bottom:0}}
.facts{{list-style:none;margin:0;padding:0}}
.facts li{{padding-left:14px;border-left:2px solid #dbe2f5;margin-bottom:12px}}
.facts li:last-child{{margin-bottom:0}}
.facts .t{{font-size:14px}} .facts .s{{font-size:12px;color:#8a909c}}
.facts.related li{{border-left-style:dashed}} .facts.related .t{{color:#4b5563}}
.cgrid{{display:flex;flex-direction:column;gap:12px}}
.cside{{border:1px solid #e4e7ec;border-radius:10px;padding:12px 14px;background:#fbfcfe}}
.cside header{{display:flex;justify-content:space-between;font-size:12px;color:#5b6270;margin-bottom:8px}}
.citem{{font-size:13px;margin-bottom:8px}} .citem:last-child{{margin-bottom:0}}
.citem .site{{font-weight:600}}
.citem .quote{{color:#5b6270}} .citem a{{font-size:12px;color:#2f5bea;word-break:break-all}}
.ev{{border:1px solid #e4e7ec;border-radius:10px;padding:12px 14px;margin-bottom:10px}}
.ev:last-child{{margin-bottom:0}}
.ev-head{{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:6px}}
.mark{{font-weight:700}} .tier{{font-size:11px;color:#4b5563;background:#eceef1;
padding:2px 8px;border-radius:99px;white-space:nowrap}}
.ev-head .title{{font-size:14px;font-weight:600;color:#16181d;text-decoration:none}}
.ev-head .title:hover{{color:#2f5bea;text-decoration:underline}}
.quote{{font-size:13px;color:#5b6270;margin:4px 0}}
.sreason{{font-size:12px;color:#8a909c;margin-bottom:4px}}
.syndtag{{font-size:11px;color:#8a5a00;background:#fdf5e3;border:1px solid #f2e0b5;
padding:1px 7px;border-radius:99px;white-space:nowrap}}
.syndnote{{font-size:12px;color:#8a5a00;background:#fdf5e3;border-left:3px solid #f2e0b5;
padding:4px 9px;margin:4px 0 6px;border-radius:0 4px 4px 0}}
.ev.ev-synd{{opacity:.86}}
.plan{{margin:0;padding-left:18px;list-style:decimal}}
.plan li{{margin-bottom:8px}}
.plan li:last-child{{margin-bottom:0}}
.pq{{font-size:13px}}
.pm{{font-size:12px;color:#8a909c;font-variant-numeric:tabular-nums}}
.audit li{{margin-bottom:8px;font-size:13.5px}} .audit li:last-child{{margin-bottom:0}}
.conddiff{{margin-top:14px;padding:12px 14px;border-radius:10px;background:#f7f9fd;border:1px dashed #cfd9ea}}
.ctitle{{font-size:13px;font-weight:700;margin-bottom:8px}}
.crow{{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap;margin-bottom:6px}}
.cside{{font-size:12px;color:#8a909c;min-width:84px}}
.cchip{{font-size:12px;padding:2px 9px;border-radius:99px;background:#eaf2fb;border:1px solid #cfe0f4;
color:#1f5fa8;white-space:nowrap}}
.cnone{{font-size:12px;color:#8a909c}}
.cnote{{margin-top:8px;font-size:12.5px;color:#5b6270}}
.numgroup{{border:1px solid #e4e7ec;border-radius:10px;padding:10px 12px;background:#fbfcfe;margin-bottom:10px}}
.numgroup:last-child{{margin-bottom:0}}
.numhead{{display:flex;gap:8px;align-items:baseline;margin-bottom:8px;flex-wrap:wrap}}
.numtag{{font-size:11px;font-weight:700;color:#8a5a00;background:#fdf5e3;border:1px solid #f2e0b5;
padding:1px 8px;border-radius:99px;white-space:nowrap}}
.numnote{{font-size:12px;color:#8a909c}}
.numrow{{display:grid;grid-template-columns:88px 150px 1fr auto;gap:8px;align-items:baseline;
font-size:12.5px;padding:5px 0;border-top:1px dashed #eceef2}}
.numrow:first-of-type{{border-top:none}}
.numval{{font-weight:700;font-variant-numeric:tabular-nums}}
.numsite{{color:#5b6270}} .numctx{{color:#8a909c}} .numrow a{{font-size:12px}}
.gaps li{{margin-bottom:8px;font-size:13.5px}} .gaps li:last-child{{margin-bottom:0}}
.ev-foot{{display:flex;gap:10px;flex-wrap:wrap;font-size:11.5px;color:#8a909c}}
.ev-foot .by{{color:#2f5bea}}
footer{{max-width:900px;margin:16px auto 0;padding:14px 18px;border:1px dashed #d8dce5;
border-radius:12px;background:#fbfbfd;font-size:12.5px;color:#5b6270}}
footer .disc{{margin-bottom:9px;padding-bottom:9px;border-bottom:1px dashed #e4e7ec;color:#8a6d1f}}
footer b{{color:#16181d}} .fp{{font-family:ui-monospace,Consolas,monospace;color:#8a909c}}
a{{color:#2f5bea}}
@media print{{
  body{{background:#fff;padding:0}}
  .card,section,footer{{box-shadow:none;break-inside:avoid}}
  .ev{{break-inside:avoid}}
}}
</style></head>
<body><div class="wrap">
  <div class="brand"><span><b>AI元宝大侦探</b> · 查得到、信得过</span><span>v{_e(card.get('version') or '—')} ｜ 指纹 <span class="fp">{fp}</span></span></div>
  {notice_html}
  <div class="card">
    <div class="q">{_e(domain_name)} ｜ {_e(MODE_TEXT.get(str(card.get('mode')), ''))} ｜ {_e(card.get('query_time'))}</div>
    <div class="verdict">{_e(card.get('verdict_label'))}</div>
    <p class="line">{_e(card.get('one_line'))}</p>
    {conf_block}
    <div class="meta">
      <div><span>领域</span>{_e(domain_name)}</div>
      <div><span>问句</span>{_e(card.get('query'))}</div>
      <div><span>检索层</span>{_e(provider_text)}</div>
      <div><span>判定引擎</span>{_e(engine_text)}<br>{_e(engine_detail)}</div>
      <div><span>检索耗时</span>{_e(card.get('elapsed_ms'))} ms</div>
      <div><span>结果流转</span>{_e(len(plan.get('queries') or []) or 1)} 路抓取 {_e(plan.get('fetched', stats.get('raw', 0)))} 条 → 采信 {_e(stats.get('used', 0))} → 可判定 {_e(stats.get('judged', 0))}</div>
      <div><span>独立来源</span>{_e(stats.get('independent_sources', 0))} 个（转载 {_e(stats.get('syndicated', 0))} 条已折减）</div>
      <div><span>生成时间</span>{_e(generated)}</div>
    </div>
  </div>
  {facts_html}
  {related_html}
  {conflict_html}
  {num_html}
  <section><h2>裁决依据</h2><ol>{reasons_html}</ol></section>
  {gaps_html}
  {audit_html}
  {plan_html}
  <section><h2>来源证据（{len(card.get('evidence') or [])}）</h2>{ev_html}</section>
  <footer>
    {disclaimer_html}
    <b>这张卡不做的事：</b>证据不足时不给结论；查不到就说「没查到可靠来源」；
    结论标签由可复现的加权规则产出，模型只负责单条证据的立场标注与文字表达。<br>
    静态快照，来源链接可能随时间失效；需要复核请以原文为准。
    规则版本 v{_e(card.get('version') or '—')}——阈值或权重改过之后，同一个问题会得出不同的卡，
    所以版本号是这张卡的一部分。
  </footer>
</div>
<script type="application/json" id="card-json">{raw_json}</script>
</body></html>"""


def save_static(card: dict, out_dir: pathlib.Path | None = None) -> pathlib.Path:
    target_dir = pathlib.Path(out_dir) if out_dir else DEFAULT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    fp = fingerprint(card)
    path = target_dir / f"card-{fp}.html"
    path.write_text(render_html(card), encoding="utf-8")
    (target_dir / f"card-{fp}.json").write_text(
        json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path
