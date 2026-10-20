const $ = (id) => document.getElementById(id);

const VERDICT_CLASS = {
  true: "ok", false: "bad", unclear: "warn",
  found: "info", no_evidence: "muted", error: "bad",
};
const MARK = { support: "＋", refute: "－", uncertain: "？", neutral: "·" };
const MODE_TEXT = { claim: "查真假", open: "查最新 / 查模糊" };

let lastCard = null;
const domainMap = {};

function currentDomain() {
  return ($("domainSel") && $("domainSel").value) || "general";
}

async function loadDomains() {
  try {
    const res = await fetch("/api/domains");
    const data = await res.json();
    const sel = $("domainSel");
    sel.innerHTML = "";
    (data.domains || []).forEach((d) => {
      domainMap[d.id] = d;
      const opt = document.createElement("option");
      opt.value = d.id;
      opt.textContent = d.name;
      sel.appendChild(opt);
    });
    sel.value = new URLSearchParams(location.search).get("domain") || "general";
    updateTagline();
    await loadSamples();
  } catch (err) {
    await loadSamples();
  }
}

function updateTagline() {
  const d = domainMap[currentDomain()];
  $("domainTagline").textContent = d ? `${d.name} · ${d.tagline}` : "";
}

async function loadSamples() {
  try {
    const res = await fetch("/api/samples?domain=" + encodeURIComponent(currentDomain()));
    const data = await res.json();
    const box = $("chips");
    box.innerHTML = "";
    (data.samples || []).forEach((item) => {
      const btn = document.createElement("button");
      btn.className = "chip";
      btn.type = "button";
      btn.textContent = item.label;
      btn.addEventListener("click", () => {
        $("q").value = item.query;
        ask(item.query);
      });
      box.appendChild(btn);
    });
  } catch (err) { /* 样例列表拿不到不影响主流程 */ }
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function tierPill(tier, label) {
  return `<span class="pill pill-t${tier}">${esc(label || "T" + tier)}</span>`;
}

async function loadHealth() {
  const pill = $("providerPill");
  try {
    const res = await fetch("/api/health");
    const data = await res.json();
    const ver = data.version ? "v" + data.version : "—";
    if ($("verPill")) $("verPill").textContent = ver;
    if ($("verPillEmpty")) $("verPillEmpty").textContent = ver;
    pill.title = data.version_notes
      ? `v${data.version} · ${data.version_notes.title || ""}`
      : "";
    if (data.provider === "wsa") {
      pill.className = "pill pill-live";
      pill.textContent = "元宝搜索 · 实时检索";
    } else {
      pill.className = "pill pill-sample";
      pill.textContent = "离线样例 · 未连接元宝搜索";
    }
  } catch (err) {
    pill.className = "pill pill-ghost";
    pill.textContent = "服务未连接";
  }
}

function domainLabel(card) {
  const d = (card && card.domain) || domainMap[currentDomain()];
  return d && d.name ? d.name : "通用查证";
}

function setActionsEnabled(on) {
  $("shareBtn").disabled = !on;
  $("copyBtn").disabled = !on;
}

function render(card) {
  lastCard = card;
  setActionsEnabled(true);
  $("empty").classList.add("hidden");
  $("result").classList.remove("hidden");

  const notice = $("notice");
  if (card.notice) {
    notice.textContent = card.notice;
    notice.classList.remove("hidden");
  } else {
    notice.classList.add("hidden");
  }

  const box = $("verdictCard");
  box.className = "verdict " + (VERDICT_CLASS[card.verdict] || "muted");
  $("verdictLabel").textContent = card.verdict_label;
  const s = card.stats || {};
  const engine = s.engine || {};
  const engineText = engine.name === "semantic"
    ? `语义判定 ${engine.semantic || 0} 条 / 词典 ${engine.lexicon || 0} 条`
    : `词典兜底 ${engine.lexicon || 0} 条`;
  const planInfo = s.plan || {};
  const synd = s.syndicated || 0;
  const indie = s.independent_sources || 0;
  $("verdictMeta").innerHTML =
    `${esc(domainLabel(card))} ｜ ${esc(MODE_TEXT[card.mode] || card.mode)} ｜ ${esc(card.provider === "wsa" ? "元宝搜索" : "离线样例")}` +
    ` ｜ ${esc(engineText)} ｜ ${card.elapsed_ms}ms ｜ ${esc(card.query_time)}` +
    ` ｜ v${esc(card.version || "—")}<br>` +
    `${(planInfo.queries || []).length || 1} 路查询共抓取 ${planInfo.fetched || s.raw || 0} 条 → 去重后采信 ${s.used || 0} 条 → 可判定 ${s.judged || 0} 条` +
    (synd ? ` ｜ 其中转载 ${synd} 条不计独立印证（独立源 ${indie} 个）` : ` ｜ 独立源 ${indie} 个`);
  $("oneLine").textContent = card.one_line || "";

  const confWrap = $("confWrap");
  if (card.confidence > 0) {
    confWrap.style.display = "flex";
    $("confBar").style.width = Math.round(card.confidence * 100) + "%";
    $("confNum").textContent = Math.round(card.confidence * 100) + "%";
  } else {
    confWrap.style.display = "none";
  }

  const factsPanel = $("factsPanel");
  if ((card.key_facts || []).length) {
    factsPanel.classList.remove("hidden");
    $("facts").innerHTML = card.key_facts.map((f) => `
      <li>
        <div class="t">${esc(f.text)}</div>
        <div class="s">${esc(f.site)}（${esc(f.tier_label)}）· ${esc(f.date || "未标注时间")} ·
          <a href="${esc(f.url)}" target="_blank" rel="noopener">原文</a></div>
      </li>`).join("");
  } else {
    factsPanel.classList.add("hidden");
  }

  const conflictPanel = $("conflictPanel");
  if ((card.conflicts || []).length) {
    conflictPanel.classList.remove("hidden");
    $("conflictGrid").innerHTML = card.conflicts.map((side) => {
      const cls = side.side.startsWith("支持") ? "support" : side.side.startsWith("否定") ? "refute" : "";
      return `<div class="conflict-side ${cls}">
        <header><span>${esc(side.side)}</span><span>权重 ${esc(side.weight ?? 0)}</span></header>
        ${(side.items || []).map((it) => `
          <div class="conflict-item">
            <div class="site">${esc(it.site || "模型说明")}</div>
            ${it.quote ? `<div class="quote">「${esc(it.quote)}」</div>` : ""}
            ${it.url ? `<a href="${esc(it.url)}" target="_blank" rel="noopener">${esc(it.url)}</a>` : ""}
          </div>`).join("")}
      </div>`;
    }).join("");
  } else {
    conflictPanel.classList.add("hidden");
  }

  // —— 条件差异：两方吵的其实不是同一件事 ——
  const cond = card.condition_diff || {};
  const condBox = $("condDiff");
  if (cond.differ) {
    const chips = (words, cls) => (words || [])
      .map((w) => `<span class="cond-chip ${cls}">${esc(w)}</span>`).join("");
    condBox.classList.remove("hidden");
    condBox.innerHTML = `
      <div class="cond-title">两方讨论的条件并不相同</div>
      <div class="cond-row">
        <span class="cond-side">${esc(cond.side_a || "一方")}</span>
        ${chips(cond.a_only, "a") || '<span class="cond-none">无额外限定</span>'}
      </div>
      <div class="cond-row">
        <span class="cond-side">${esc(cond.side_b || "另一方")}</span>
        ${chips(cond.b_only, "b") || '<span class="cond-none">无额外限定</span>'}
      </div>
      ${(cond.shared || []).length
        ? `<div class="cond-row shared"><span class="cond-side">双方共同限定</span>${chips(cond.shared, "s")}</div>`
        : ""}
      <div class="cond-note">这更像两个不同条件下的两个结论，不宜按同一句话裁决——先确认你关心的是哪一种情形。</div>`;
  } else {
    condBox.classList.add("hidden");
    condBox.innerHTML = "";
  }

  // —— 关键数字核对：只提示，不参与裁决 ——
  const numbersPanel = $("numbersPanel");
  if ((card.numbers || []).length) {
    numbersPanel.classList.remove("hidden");
    $("numbers").innerHTML = card.numbers.map((g) => `
      <div class="numgroup">
        <div class="numhead">
          <span class="numtag">${esc(g.label)}</span>
          <span class="numnote">${esc(g.note)}</span>
        </div>
        ${(g.values || []).map((v) => `
          <div class="numrow">
            <span class="numval">${esc(v.shown)}</span>
            <span class="numsite">${esc(v.site)}</span>
            <span class="numctx">${esc(v.ctx)}</span>
            ${v.url ? `<a href="${esc(v.url)}" target="_blank" rel="noopener">原文</a>` : ""}
          </div>`).join("")}
      </div>`).join("");
  } else {
    numbersPanel.classList.add("hidden");
  }

  // —— 最小补证清单 ——
  const gaps = card.gaps || [];
  if (gaps.length) {
    $("gapsPanel").classList.remove("hidden");
    $("gaps").innerHTML = gaps.map((g) => `<li>${esc(g)}</li>`).join("");
  } else {
    $("gapsPanel").classList.add("hidden");
  }

  $("reasons").innerHTML = (card.reasons || []).map((r) => `<li>${esc(r)}</li>`).join("");

  // —— 检索路线：多路问法 + 每路捞回多少条、其中多少是新出现的 ——
  const plan = s.plan || {};
  const trace = plan.trace || [];
  const planPanel = $("planPanel");
  if (trace.length) {
    planPanel.classList.remove("hidden");
    $("planCount").textContent = `(${trace.length} 路 · 去重后 ${plan.unique || 0} 条)`;
    $("plan").innerHTML = trace.map((t, i) => `
      <li>
        <div class="plan-q"><span class="plan-idx">${i + 1}</span>${esc(t.query)}</div>
        <div class="plan-meta">
          ${t.error
            ? `<span class="plan-err">${esc(t.error)}</span>`
            : `捞回 ${t.hits} 条 · 新增 ${t.new} 条`}
        </div>
      </li>`).join("");
  } else {
    planPanel.classList.add("hidden");
  }

  // —— 推翻路径 ——
  const audit = card.audit_steps || [];
  if (audit.length) {
    $("auditPanel").classList.remove("hidden");
    $("audit").innerHTML = audit.map((a) => `<li>${esc(a)}</li>`).join("");
  } else {
    $("auditPanel").classList.add("hidden");
  }

  $("evidenceCount").textContent = `(${(card.evidence || []).length})`;
  $("evidence").innerHTML = (card.evidence || []).map((ev) => `
    <div class="ev${ev.is_syndicated ? " ev-synd" : ""}">
      <div class="ev-head">
        <span class="mark ${esc(ev.stance)}">${MARK[ev.stance] || "·"}</span>
        ${tierPill(ev.tier, ev.tier_label)}
        <span class="by-tag ${ev.stance_by === "semantic" ? "sem" : "lex"}">${ev.stance_by === "semantic" ? "语义" : "词典"}</span>
        ${ev.is_syndicated ? `<span class="by-tag synd" title="与原始来源文字高度重合，按转载计权">转载</span>` : ""}
        <span class="ev-title"><a href="${esc(ev.url)}" target="_blank" rel="noopener">${esc(ev.title || ev.url)}</a></span>
      </div>
      <div class="ev-quote">「${esc(ev.quote)}」</div>
      ${ev.stance_reason ? `<div class="ev-reason">判定理由：${esc(ev.stance_reason)}</div>` : ""}
      ${ev.is_syndicated && ev.syndicated_site ? `<div class="ev-synd-note">原文出自《${esc(ev.syndicated_site)}》，本条为转载，权重已减半</div>` : ""}
      <div class="ev-foot">
        <span>${esc(ev.site)}</span>
        <span>${esc(ev.date || "未标注时间")}</span>
        <span class="num">相关性 ${Number(ev.score).toFixed(2)}</span>
        <span class="num">权重 ${Number(ev.weight).toFixed(2)}</span>
        <span>${esc(ev.stance_label)}</span>
      </div>
    </div>`).join("") || `<div class="skeleton">没有可展示的证据</div>`;

  const disc = $("disclaimer");
  const domainInfo = card.domain || domainMap[currentDomain()] || {};
  if (domainInfo.disclaimer) {
    disc.textContent = domainInfo.disclaimer;
    disc.classList.remove("hidden");
  } else {
    disc.classList.add("hidden");
  }
}

async function ask(query) {
  const q = (query || "").trim();
  if (!q) return;
  const btn = $("askBtn");
  btn.disabled = true;
  btn.textContent = "查证中…";
  setActionsEnabled(false);
  $("result").classList.add("hidden");
  $("empty").classList.add("hidden");
  $("notice").classList.add("hidden");
  const shell = document.createElement("div");
  shell.className = "skeleton";
  shell.id = "loading";
  shell.textContent = "正在检索 → 分级 → 交叉比对……";
  document.querySelector("main").appendChild(shell);

  try {
    const res = await fetch("/api/check?q=" + encodeURIComponent(q) +
      "&domain=" + encodeURIComponent(currentDomain()));
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    render(data);
  } catch (err) {
    lastCard = null;
    setActionsEnabled(false);
    $("result").classList.remove("hidden");
    $("verdictCard").className = "verdict bad";
    $("verdictLabel").textContent = "查询失败";
    $("verdictMeta").textContent = "";
    $("oneLine").textContent = "检索层没有正常返回：" + err.message;
    $("confWrap").style.display = "none";
    $("factsPanel").classList.add("hidden");
    $("conflictPanel").classList.add("hidden");
    $("reasons").innerHTML = "<li>检查服务是否仍在运行，以及 .env 里的密钥配置。</li>";
    $("evidence").innerHTML = "";
    $("evidenceCount").textContent = "(0)";
    $("planPanel").classList.add("hidden");
    $("auditPanel").classList.add("hidden");
    $("numbersPanel").classList.add("hidden");
    $("gapsPanel").classList.add("hidden");
  } finally {
    const loading = $("loading");
    if (loading) loading.remove();
    btn.disabled = false;
    btn.textContent = "查证";
  }
}

$("askForm").addEventListener("submit", (event) => {
  event.preventDefault();
  ask($("q").value);
});

$("shareBtn").addEventListener("click", () => {
  if (!lastCard) return;
  const url = "/api/card?q=" + encodeURIComponent(lastCard.query) +
    "&domain=" + encodeURIComponent((lastCard.domain && lastCard.domain.id) || currentDomain()) +
    "&provider=" + encodeURIComponent(lastCard.provider || "");
  window.open(url, "_blank", "noopener");
});

$("copyBtn").addEventListener("click", async () => {
  if (!lastCard) return;
  const btn = $("copyBtn");
  try {
    await navigator.clipboard.writeText(JSON.stringify(lastCard, null, 2));
    btn.textContent = "已复制";
    btn.classList.add("copied");
    setTimeout(() => {
      btn.textContent = "复制 JSON";
      btn.classList.remove("copied");
    }, 1600);
  } catch (err) {
    btn.textContent = "复制失败";
    setTimeout(() => { btn.textContent = "复制 JSON"; }, 1600);
  }
});

$("domainSel").addEventListener("change", async (event) => {
  updateTagline();
  $("result").classList.add("hidden");
  $("empty").classList.remove("hidden");
  const url = new URL(location.href);
  url.searchParams.set("domain", event.target.value);
  url.searchParams.delete("q");
  history.replaceState(null, "", url);
  await loadSamples();
});

loadHealth();
loadDomains();

// 支持 ?q=xxx 直接出卡，方便分享单个查证结果
const preset = new URLSearchParams(location.search).get("q");
if (preset) {
  $("q").value = preset;
  ask(preset);
}
