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
  const btn = $("wsaBtn");
  try {
    const res = await fetch("/api/health");
    const data = await res.json();
    const ver = data.version ? "v" + data.version : "—";
    if ($("verPill")) $("verPill").textContent = ver;
    if ($("verPillEmpty")) $("verPillEmpty").textContent = ver;
    paintProvider(data);
  } catch (err) {
    if (!btn) return;
    btn.classList.remove("is-live", "is-sample");
    btn.title = "服务未连接";
  }
}

// 入口按钮只表达一件事：现在连没连上。颜色留给结论，不跟这里抢。
function paintProvider(data) {
  const btn = $("wsaBtn");
  if (!btn) return;
  const live = data.provider === "wsa";
  btn.classList.toggle("is-live", live);
  btn.classList.toggle("is-sample", !live);
  const masked = data.secret_id_masked ? `（${data.secret_id_masked}）` : "";
  if (live) {
    btn.title = `元宝搜索已连接${masked}，当前走实时检索 · 点击可修改密钥`;
  } else if (data.provider_setting === "mock") {
    btn.title = "未连接元宝搜索（.env 里强制定了离线样例）· 点击填入密钥";
  } else {
    btn.title = "未连接元宝搜索，当前为离线样例 · 点击填入 SecretId / SecretKey";
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

// —— 日间 / 夜间 ——
// 主题存在 localStorage，没存过就跟随系统；切换后要通知粒子层重读颜色变量。
const THEME_KEY = "detective-theme";

function savedTheme() {
  try { return localStorage.getItem(THEME_KEY); } catch (err) { return null; }
}

function applyTheme(theme, persist) {
  const next = theme === "dark" ? "dark" : "light";
  document.documentElement.setAttribute("data-theme", next);
  const btn = $("themeBtn");
  if (btn) {
    btn.setAttribute("aria-checked", String(next === "dark"));
    btn.title = next === "dark" ? "当前：夜间样式，点击切到日间" : "当前：日间样式，点击切到夜间";
  }
  if (persist) {
    try { localStorage.setItem(THEME_KEY, next); } catch (err) { /* 写不进去也不影响本次渲染 */ }
  }
  if (window.Particles && window.Particles.setTheme) window.Particles.setTheme();
}

function initTheme() {
  const prefersDark = !!(window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
  // ?theme=dark / ?theme=light 可以直接指定配色，优先于本地记忆
  const forced = new URLSearchParams(location.search).get("theme");
  const initial = (forced === "dark" || forced === "light")
    ? forced
    : (savedTheme() || (prefersDark ? "dark" : "light"));
  applyTheme(initial, false);

  const btn = $("themeBtn");
  if (btn) {
    btn.addEventListener("click", () => {
      const now = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
      applyTheme(now, true);
    });
  }

  // 用户没手动选过时，跟着系统的日夜设置走
  if (window.matchMedia) {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onSchemeChange = (e) => {
      if (!savedTheme()) applyTheme(e.matches ? "dark" : "light", false);
    };
    if (mq.addEventListener) mq.addEventListener("change", onSchemeChange);
    else if (mq.addListener) mq.addListener(onSchemeChange);
  }
}

// —— 元宝搜索设置 ——
// 保存 = 写本机 .env 并热生效；测试 = 真打一次 SearchPro 看通不通。
// 两个动作分开，是因为「保存成功」和「密钥能用」不是同一件事，混在一起最容易让人误判。
//
// 人性化的一条：**测通过之后点保存，窗口自己关掉**。测试通过说明这两把钥匙已经验证过，
// 用户此时唯一的下一步就是回去提问；还让他伸手点 × 属于把流程成本转嫁给用户。
// 反过来，没测过就保存时窗口不关——那种「存完才发现密钥是错的」最容易让人怀疑没存上，
// 留着窗口让他顺手点一次测试，比关掉再重新打开体贴。
let settingsReturnFocus = null;
// untested = 当前输入框里的值还没通过测试。输入一变就置 true，测过就置 false。
const settingsState = { untested: true };

function setResult(kind, text) {
  const box = $("setResult");
  if (!box) return;
  if (!kind) {
    box.className = "set-result hidden";
    box.innerHTML = "";
    return;
  }
  const icon = kind === "ok" ? "✓" : kind === "bad" ? "✕" : "!";
  box.className = "set-result " + kind;
  box.innerHTML = `<span class="sr-ico">${icon}</span><span class="sr-body">${esc(text)}</span>`;
}

function paintSettingsStatus(status) {
  const box = $("setStatus");
  const txt = $("setStatusText");
  if (!box || !txt) return;
  box.className = "set-status";
  if (!status) {
    txt.textContent = "读不到当前配置，可以直接填写后保存";
    return;
  }
  const live = status.has_wsa && status.provider === "wsa";
  if (live) {
    box.classList.add("live");
    const from = status.source === "file" ? "本机 .env" : status.source === "env" ? "环境变量" : "已保存";
    txt.textContent = `已连接：SecretId ${status.secret_id_masked || "已保存"}（来自${from}）`;
  } else if (status.has_wsa) {
    box.classList.add("sample");
    txt.textContent = "密钥已保存，但当前被强制成离线样例（PROVIDER=mock）";
  } else {
    box.classList.add("sample");
    txt.textContent = "未连接元宝搜索，当前是离线样例（demo/fixtures.json）";
  }
  $("setSid").placeholder = status.secret_id_masked
    ? `已保存 ${status.secret_id_masked}，填新的会覆盖`
    : "AKIDxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx";
  $("setSkey").placeholder = status.secret_key_set
    ? "已保存，填新的会覆盖"
    : "创建 API 密钥时生成的那一串";
  $("setClear").disabled = !status.has_wsa;
}

async function refreshSettings() {
  try {
    const res = await fetch("/api/settings");
    const status = await res.json();
    paintSettingsStatus(status);
    return status;
  } catch (err) {
    paintSettingsStatus(null);
    return null;
  }
}

async function openSettings() {
  settingsReturnFocus = document.activeElement;
  settingsState.untested = true;
  $("settingsModal").classList.remove("hidden");
  document.body.classList.add("modal-open");
  setResult(null);
  paintSettingsStatus(null);
  await refreshSettings();
  setTimeout(() => $("setSid").focus(), 60);
}

function closeSettings() {
  $("settingsModal").classList.add("hidden");
  document.body.classList.remove("modal-open");
  if (settingsReturnFocus && settingsReturnFocus.focus) settingsReturnFocus.focus();
}

// 保存成功后的收尾：该关就关，该留就留。
function finishSave(autoClose, notes) {
  const extra = notes ? " " + notes : "";
  setResult("ok", autoClose
    ? `已保存到本机 .env，立即生效。${extra}窗口即将关闭。`
    : `已保存到本机 .env，立即生效。${extra}这对密钥还没测过，点「测试连接」确认一次——验证通过后窗口就会自己关掉。`);
  if (autoClose) {
    setTimeout(() => {
      if (!$("settingsModal").classList.contains("hidden")) closeSettings();
    }, 1500);
  }
}

async function submitSettings(action) {
  const isTest = action === "test";
  const sid = $("setSid").value.trim();
  const skey = $("setSkey").value.trim();

  if (!isTest && (!sid || !skey)) {
    setResult("bad", "SecretId 和 SecretKey 要一起填。已经存过的话，两栏留空、直接点「测试连接」就行。");
    return;
  }
  if (isTest && !sid && !skey && $("setClear").disabled) {
    setResult("bad", "还没有可测试的密钥，先填两栏再测。");
    return;
  }

  const btn = isTest ? $("setTest") : $("setSave");
  const label = btn.textContent;
  btn.disabled = true;
  btn.textContent = isTest ? "测试中…" : "保存中…";
  if (isTest) setResult("warn", "正在请求元宝搜索 SearchPro，最多等 12 秒…");

  try {
    const res = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, secret_id: sid, secret_key: skey }),
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);

    if (isTest) {
      const probe = data.probe || {};
      const scope = data.tested_saved ? "（用已保存的密钥）" : "";
      if (probe.ok) {
        settingsState.untested = false;
        setResult("ok", `连接成功${scope}：${probe.message} 现在点「保存」，窗口会自己关掉。`);
      } else {
        settingsState.untested = true;
        setResult("bad", `连接失败${scope}：${probe.message || "没拿到原因"}`);
      }
    } else {
      const notes = (data.notes || []).join("；");
      if (data.warning) {
        setResult("warn", `${data.warning}${notes ? " " + notes : ""} 点「测试连接」确认一次。`);
      } else {
        finishSave(!settingsState.untested, notes);
      }
      // 存完就把输入框清空：状态行和占位符已经说明「存的是什么」，留着旧值反而让人怀疑没存上
      $("setSid").value = "";
      $("setSkey").value = "";
      // 输入框空了，等于又是「一对没测过的值」
      settingsState.untested = true;
      await refreshSettings();
    }
    await loadHealth();
  } catch (err) {
    setResult("bad", `${isTest ? "测试" : "保存"}失败：${err.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = label;
  }
}

async function clearSettings() {
  if (!confirm("清除后检索层会回到离线样例，确定吗？")) return;
  const btn = $("setClear");
  btn.disabled = true;
  try {
    const res = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "clear" }),
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    setResult("ok", "已清除密钥，检索层回到离线样例。");
    $("setSid").value = "";
    $("setSkey").value = "";
    await refreshSettings();
    await loadHealth();
  } catch (err) {
    setResult("bad", "清除失败：" + err.message);
  } finally {
    btn.disabled = false;
  }
}

$("wsaBtn").addEventListener("click", openSettings);
$("settingsClose").addEventListener("click", closeSettings);
$("setSave").addEventListener("click", () => submitSettings("save"));
$("setTest").addEventListener("click", () => submitSettings("test"));
$("setClear").addEventListener("click", clearSettings);
$("settingsModal").addEventListener("click", (event) => {
  if (event.target === $("settingsModal")) closeSettings();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !$("settingsModal").classList.contains("hidden")) closeSettings();
});
$("setEye").addEventListener("click", () => {
  const input = $("setSkey");
  const reveal = input.type === "password";
  input.type = reveal ? "text" : "password";
  $("setEye").textContent = reveal ? "隐藏" : "显示";
  $("setEye").setAttribute("aria-label", reveal ? "隐藏 SecretKey" : "显示 SecretKey");
});
// 粘贴时把首尾的空白和引号一并清掉——从控制台复制经常带进来
["setSid", "setSkey"].forEach((id) => {
  $(id).addEventListener("input", () => { settingsState.untested = true; });
  $(id).addEventListener("blur", () => {
    const el = $(id);
    el.value = el.value.trim().replace(/^["']|["']$/g, "");
  });
});

initTheme();
if (window.Particles) window.Particles.init($("particles"));
loadHealth();
loadDomains();

// 支持 ?q=xxx 直接出卡，方便分享单个查证结果
const preset = new URLSearchParams(location.search).get("q");
if (preset) {
  $("q").value = preset;
  ask(preset);
}
