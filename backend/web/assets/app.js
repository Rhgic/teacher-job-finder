/* 教师求职 Demo · 共享脚本
   同源部署（FastAPI StaticFiles 挂载），fetch 直接打相对路径，无 CORS。 */

/* 体验身份令牌：存在则所有请求自动携带；不存在时后端(dev 模式)回退 demo 用户 */
const TOKEN_KEY = "tjf_guest_token";
const getToken = () => localStorage.getItem(TOKEN_KEY);
const clearToken = () => localStorage.removeItem(TOKEN_KEY);

class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const api = async (path, options = {}) => {
  const headers = { ...(options.headers || {}) };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const resp = await fetch(path, { ...options, headers });
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try { detail = (await resp.json()).detail || detail; } catch (_) { /* 非 JSON 响应 */ }
    throw new ApiError(resp.status, detail);
  }
  return resp.json();
};

async function ensureGuest() {
  if (getToken()) return getToken();
  const d = await api("/auth/guest", { method: "POST" });
  localStorage.setItem(TOKEN_KEY, d.token);
  return d.token;
}

function showIdentityRequired(box, pageName) {
  // 生产密钥轮换后，浏览器里的旧令牌也会失效；先清掉，确保「我的」页
  // 能重新展示“创建体验身份”按钮。这里不静默创建身份，仍由用户明确点击。
  clearToken();
  box.innerHTML = `<div class="state">
    <div class="big">查看${esc(pageName)}前，请先创建体验身份</div>
    <div>去<a class="cta-inline" href="me.html">「我的」页</a>点击“创建体验身份”，再回来查看</div>
  </div>`;
}

/* 与 miniprogram/utils/api.js 的 buildJobTitle 同一逻辑：
   学校名已含学段时不重复拼接，避免"小学小学"。 */
function buildJobTitle(job = {}) {
  const school = (job.school_name || "").trim();
  const stage = (job.stage || "").trim();
  const subject = (job.subject || "").trim();
  const parts = [];
  if (school) parts.push(school);
  if (stage && !school.endsWith(stage)) parts.push(stage);
  if (subject) parts.push(subject);
  return `${parts.join("") || "教师"}招聘`;
}

function fmtSalary(min, max) {
  const w = (n) => {
    const v = n / 10000;
    return (v % 1 === 0 ? v.toFixed(0) : v.toFixed(1));
  };
  if (min && max) return `月薪 ${w(min)}–${w(max)} 万`;
  if (min) return `月薪 ${w(min)} 万起`;
  if (max) return `月薪最高 ${w(max)} 万`;
  return "薪资详见公告";
}

function deadlineInfo(deadline) {
  if (!deadline) return { text: "长期有效", cls: "" };
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const d = new Date(`${deadline}T00:00:00`);
  const days = Math.round((d - today) / 86400000);
  if (days < 0) return { text: "已截止", cls: "over" };
  if (days === 0) return { text: "今天截止", cls: "warn" };
  if (days <= 7) return { text: `剩 ${days} 天截止`, cls: "warn" };
  return { text: `${deadline} 截止`, cls: "" };
}

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
));

const SCHOOL_TYPE_ZH = { public: "公办", private: "民办", training: "培训机构" };
const schoolTypeZh = (t) => SCHOOL_TYPE_ZH[t] || t;

/* 下拉多选面板：把成排的选项收进一个触发器里，避免平铺成墙。
   触发器显示已选数量，面板内多选，面板外点击/Esc 关闭。
   counts 可选：岗位页要展示每个选项有多少岗位，「我的」页设求职意向则不需要。 */
function createPicker(host, { key, label, options, selected, onChange, counts }) {
  const badge = (o) => (counts && counts[o] != null
    ? `<span class="pi-n num">${counts[o]}</span>` : "");
  host.insertAdjacentHTML("beforeend", `
    <div class="picker" data-key="${key}">
      <button type="button" class="picker-trigger" aria-expanded="false" aria-haspopup="true">
        <span class="label">${esc(label)}</span>
        <span class="summary"></span>
        <span class="caret">▼</span>
      </button>
      <div class="picker-panel" hidden role="group" aria-label="${esc(label)}选项">
        <div class="picker-grid">
          ${options.map((o) => `
            <button type="button" class="picker-item" data-v="${esc(o)}" aria-pressed="false">${esc(o)}${badge(o)}</button>`).join("")}
        </div>
        <div class="picker-foot">
          <button type="button" class="clear">清空</button>
          <button type="button" class="done">完成</button>
        </div>
      </div>
    </div>`);

  const root = host.lastElementChild;
  const trigger = root.querySelector(".picker-trigger");
  const panel = root.querySelector(".picker-panel");
  const summary = root.querySelector(".summary");

  function paint() {
    root.querySelectorAll(".picker-item").forEach((item) => {
      const on = selected.has(item.dataset.v);
      item.classList.toggle("on", on);
      item.setAttribute("aria-pressed", String(on));
    });
    const n = selected.size;
    summary.innerHTML = n
      ? `<span class="count num">${n}</span>`
      : "不限";
    onChange();
  }

  function close() {
    root.classList.remove("open");
    panel.hidden = true;
    trigger.setAttribute("aria-expanded", "false");
  }
  function open() {
    document.querySelectorAll(".picker.open").forEach((p) => {
      p.classList.remove("open");
      p.querySelector(".picker-panel").hidden = true;
      p.querySelector(".picker-trigger").setAttribute("aria-expanded", "false");
    });
    root.classList.add("open");
    panel.hidden = false;
    trigger.setAttribute("aria-expanded", "true");
  }

  trigger.addEventListener("click", () => (root.classList.contains("open") ? close() : open()));
  panel.addEventListener("click", (ev) => {
    const item = ev.target.closest(".picker-item");
    if (item) {
      const v = item.dataset.v;
      selected.has(v) ? selected.delete(v) : selected.add(v);
      paint();
      return;
    }
    if (ev.target.closest(".clear")) { selected.clear(); paint(); return; }
    if (ev.target.closest(".done")) close();
  });
  root.addEventListener("keydown", (ev) => { if (ev.key === "Escape") { close(); trigger.focus(); } });

  paint();
  return { close, paint };
}

/* ---------- 岗位页 ---------- */
async function initJobsPage() {
  const grid = document.getElementById("grid");
  const statsEl = document.getElementById("stats");
  const filtersEl = document.getElementById("filters");
  const countEl = document.getElementById("resultCount");
  let jobs = [];
  // 多选：可同时看南山区 + 福田区，比单选实用
  const active = {
    district: new Set(), stage: new Set(), subject: new Set(), bianzhi: false,
  };

  try {
    jobs = await api("/jobs?size=100");
  } catch (e) {
    grid.innerHTML = `<div class="state">
      <div class="big">连不上后端接口</div>
      <div>${esc(e.message)}</div>
      <div>本地演示请先启动：<code>uvicorn main:app --port 8000</code></div>
    </div>`;
    return;
  }

  const uniq = (key) => [...new Set(jobs.map((j) => j[key]).filter(Boolean))];
  const count = (key, v) => jobs.filter((j) => j[key] === v).length;

  statsEl.innerHTML = `
    <div class="stat"><div class="v num">${jobs.length}</div><div class="k">在招岗位</div></div>
    <div class="stat"><div class="v num">${uniq("district").length}</div><div class="k">覆盖区域</div></div>
    <div class="stat"><div class="v num">${jobs.filter((j) => j.is_establishment).length}</div><div class="k">带编制</div></div>
    <a class="stat ai" href="recommend.html"><div class="v num" id="aiStat">AI</div><div class="k">智能推荐 →</div></a>`;

  // 选项与计数都从当前数据推导：筛一个 0 结果的条件没有意义。
  // （「我的」页设求职意向则相反，用后端标准表——两处语义不同，别混用。）
  const countsOf = (key) => Object.fromEntries(
    uniq(key).map((v) => [v, count(key, v)]));
  const byCountDesc = (key) => uniq(key).sort((a, b) => count(key, b) - count(key, a));

  filtersEl.innerHTML = "";
  const pickers = [];
  [["district", "区域"], ["stage", "学段"], ["subject", "学科"]].forEach(([key, label]) => {
    pickers.push(createPicker(filtersEl, {
      key, label,
      options: byCountDesc(key),
      counts: countsOf(key),
      selected: active[key],
      onChange: render,
    }));
  });

  // 编制是布尔项，用同样外观的开关而非下拉
  filtersEl.insertAdjacentHTML("beforeend", `
    <div class="picker" data-key="bianzhi">
      <button type="button" class="picker-trigger" id="jobBianzhi" aria-pressed="false">
        <span class="label">只看带编制</span>
        <span class="pi-n num">${jobs.filter((j) => j.is_establishment).length}</span>
      </button>
    </div>`);
  const bz = document.getElementById("jobBianzhi");
  bz.addEventListener("click", () => {
    active.bianzhi = !active.bianzhi;
    bz.classList.toggle("on", active.bianzhi);
    bz.setAttribute("aria-pressed", String(active.bianzhi));
    render();
  });

  document.addEventListener("click", (ev) => {
    if (!ev.target.closest(".picker")) pickers.forEach((p) => p.close());
  });

  function render() {
    const hit = (set, value) => set.size === 0 || set.has(value);
    const list = jobs.filter((j) =>
      hit(active.district, j.district) &&
      hit(active.stage, j.stage) &&
      hit(active.subject, j.subject) &&
      (!active.bianzhi || j.is_establishment));

    const chosen = active.district.size + active.stage.size + active.subject.size
      + (active.bianzhi ? 1 : 0);
    countEl.innerHTML = chosen
      ? `筛出 <span class="num">${list.length}</span> / ${jobs.length} 个岗位
         <button type="button" class="reset" id="resetFilters">清除筛选</button>`
      : `共 <span class="num">${jobs.length}</span> 个在招岗位`;
    const reset = document.getElementById("resetFilters");
    if (reset) {
      reset.addEventListener("click", () => {
        active.district.clear(); active.stage.clear(); active.subject.clear();
        active.bianzhi = false;
        bz.classList.remove("on");
        bz.setAttribute("aria-pressed", "false");
        pickers.forEach((p) => p.paint());
        render();
      });
    }

    if (!list.length) {
      grid.innerHTML = `<div class="state"><div class="big">没有符合筛选的岗位</div><div>换个条件试试</div></div>`;
      return;
    }
    grid.innerHTML = list.map((j, i) => {
      const dl = deadlineInfo(j.deadline);
      const salary = fmtSalary(j.salary_min, j.salary_max);
      return `
      <article class="job-card rise" style="animation-delay:${Math.min(i * 40, 400)}ms">
        <div class="job-head">
          <h3 class="job-title"><a href="job.html?id=${encodeURIComponent(j.id)}">${esc(buildJobTitle(j))}</a></h3>
          ${j.is_establishment ? '<span class="tag-bianzhi">有编制</span>' : ""}
        </div>
        <div class="job-meta">
          ${j.district ? `<span class="meta-tag">${esc(j.district)}</span>` : ""}
          ${j.stage ? `<span class="meta-tag">${esc(j.stage)}</span>` : ""}
          ${j.subject ? `<span class="meta-tag">${esc(j.subject)}</span>` : ""}
          ${j.school_type ? `<span class="meta-tag">${esc(schoolTypeZh(j.school_type))}</span>` : ""}
        </div>
        <div class="job-foot">
          <span class="salary ${j.salary_min || j.salary_max ? "" : "na"}">${salary}</span>
          <span class="deadline ${dl.cls}">${dl.text}</span>
        </div>
        <div class="job-link"><a href="job.html?id=${encodeURIComponent(j.id)}">查看详情与公告正文 →</a></div>
      </article>`;
    }).join("");
  }
  render();
}

/* ---------- 推荐页（成绩单） ---------- */
const RING_R = 42;
const RING_C = 2 * Math.PI * RING_R;

function scoreRing(score) {
  const target = score == null ? 0 : Math.max(0, Math.min(100, score));
  const offset = RING_C * (1 - target / 100);
  return `
    <div class="ring" data-score="${target}">
      <svg width="96" height="96" viewBox="0 0 96 96">
        <circle class="track" cx="48" cy="48" r="${RING_R}" fill="none" stroke-width="8"/>
        <circle class="bar" cx="48" cy="48" r="${RING_R}" fill="none" stroke-width="8"
          stroke-dasharray="${RING_C}" stroke-dashoffset="${RING_C}"/>
      </svg>
      <div class="val"><span class="n num">–</span><small>分</small></div>
    </div>`;
}

function animateRings() {
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  document.querySelectorAll(".ring").forEach((ring) => {
    const target = Number(ring.dataset.score);
    const bar = ring.querySelector(".bar");
    const num = ring.querySelector(".val .n");
    const offset = RING_C * (1 - target / 100);
    if (reduced) { bar.style.strokeDashoffset = offset; num.textContent = target || "–"; return; }
    requestAnimationFrame(() => { bar.style.strokeDashoffset = offset; });
    const t0 = performance.now();
    const tick = (t) => {
      const p = Math.min((t - t0) / 900, 1);
      num.textContent = target ? Math.round(target * (1 - Math.pow(1 - p, 3))) : "–";
      if (p < 1 && target) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
}

/* 分数拆解：命中点与差距。

   这是「75 分」和「为什么是 75 分」的区别。模型本来就按条输出了这两项，
   只展示一个总分等于把可解释性丢掉。差距同样要显示——只报命中点会让
   每个岗位看起来都很合适，用户反而没法排序。 */
function breakdown(m) {
  const hits = (m.matched_points || []).filter(Boolean);
  const gaps = (m.gaps || []).filter(Boolean);
  if (!hits.length && !gaps.length) return "";
  const row = (cls, label, items) => items.length ? `
    <div class="bd-row ${cls}">
      <span class="bd-label">${label}</span>
      <div class="bd-items">${items.map((t) => `<span class="bd-chip">${esc(t)}</span>`).join("")}</div>
    </div>` : "";
  return `<div class="breakdown">
    ${row("bd-hit", "✓ 命中", hits)}
    ${row("bd-gap", "△ 差距", gaps)}
  </div>`;
}

async function initRecommendPage() {
  const box = document.getElementById("matches");
  let items = [];
  try {
    items = await api("/recommendations");
  } catch (e) {
    if (e.status === 401) {
      showIdentityRequired(box, "个性化推荐");
      return;
    }
    box.innerHTML = `<div class="state">
      <div class="big">连不上后端接口</div><div>${esc(e.message)}</div>
      <div>本地演示请先启动：<code>uvicorn main:app --port 8000</code></div></div>`;
    return;
  }
  if (!items.length) {
    box.innerHTML = getToken()
      ? `<div class="state">
          <div class="big">你的体验身份还没有匹配结果</div>
          <div>去<a href="me.html" style="color:var(--brand)">「我的」</a>粘贴简历、圈定求职范围，然后运行 AI 匹配</div></div>`
      : `<div class="state">
          <div class="big">还没有推荐结果</div>
          <div>想看 AI 怎么匹配你自己？去<a href="me.html" style="color:var(--brand)">「我的」</a>开始体验</div></div>`;
    return;
  }

  box.innerHTML = items.map((m, i) => {
    const j = m.job || {};
    const dl = deadlineInfo(j.deadline);
    const reason = m.match_reason || "（规则层已命中，等待 AI 精排评语）";
    const confirmed = m.status === "confirmed";
    // llm_score 为空 = 这条没被模型评上（调用失败或还没跑）。
    // 此时 match_reason 里存的是"LLM 匹配失败：xxx"这类内部错误，
    // 把它塞进「AI 匹配评语」等于拿一句用户看不懂也没法处理的报错冒充评价。
    // 内部原因留在库和日志里，界面只说清状态和下一步。
    const scored = m.llm_score != null;
    return `
    <section class="match-card rise" style="animation-delay:${Math.min(i * 60, 300)}ms" data-mid="${esc(m.id)}" data-jid="${esc(j.id || "")}">
      <div class="scorebox">
        ${scoreRing(m.llm_score)}
        <span class="cap">AI 匹配分</span>
      </div>
      <div class="match-head">
        <div>
          <h3 class="match-title">${esc(buildJobTitle(j))}</h3>
          <div class="match-sub">
            <span>${esc(j.district || "")}</span>
            ${j.is_establishment ? '<span class="tag-bianzhi">有编制</span>' : ""}
            <span class="num">${esc(fmtSalary(j.salary_min, j.salary_max))}</span>
            <span class="deadline ${dl.cls}">${dl.text}</span>
          </div>
        </div>
      </div>
      <div>
        ${scored ? `
        <div class="remark">
          <span class="eyebrow">✦ AI 匹配评语</span>
          <div>${esc(reason)}</div>
        </div>
        ${breakdown(m)}` : `
        <div class="remark remark-muted">
          <span class="eyebrow">AI 暂未完成评分</span>
          <div>这个岗位通过了规则层的硬条件，但 AI 精排没有成功。
          可以先看岗位详情自行判断，或稍后回「我的」重新运行匹配。</div>
        </div>`}
        ${m.cover_letter ? `
        <details class="cover">
          <summary>AI 起草的求职信</summary>
          <div class="cover-body">${esc(m.cover_letter)}</div>
        </details>` : ""}
        <div class="match-actions">
          ${confirmed
            ? '<button class="btn btn-done">已确认投递</button>'
            : `<a class="btn btn-primary" href="apply.html?job=${encodeURIComponent(j.id || "")}&match=${encodeURIComponent(m.id)}">去投递</a>
               <a class="btn btn-ghost" href="job.html?id=${encodeURIComponent(j.id || "")}">看岗位详情</a>`}
          <span class="action-note">${confirmed ? "" : "下一步可挑选简历、确认邮件主题"}</span>
        </div>
      </div>
    </section>`;
  }).join("");

  animateRings();

}

/* ---------- 问答页 ---------- */

/* 极简 markdown 渲染：只支持加粗、无序列表、段落/换行。
   先整体转义再做替换，模型输出不会注入 HTML。 */
function renderAnswer(text) {
  const safe = esc(text);
  const blocks = safe.split(/\n{2,}/).map((block) => {
    const lines = block.split("\n");
    const isList = lines.every((l) => /^\s*[-•]\s+/.test(l) || !l.trim());
    if (isList && lines.some((l) => l.trim())) {
      const items = lines.filter((l) => l.trim())
        .map((l) => `<li>${l.replace(/^\s*[-•]\s+/, "")}</li>`).join("");
      return `<ul>${items}</ul>`;
    }
    return `<p>${block.replace(/\n/g, "<br>")}</p>`;
  }).join("");
  return blocks.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
}

const NOT_FOUND_TEXT = "公告未提及";

function qaItemHtml(question, resp) {
  const notFound = !resp.found || (resp.answer || "").includes(NOT_FOUND_TEXT);
  const cites = (resp.sources || []).map((s, i) => `
    <details class="cite">
      <summary><span class="no num">${i + 1}</span>${esc(s.title || "公告片段")}</summary>
      <div class="snippet">${esc(s.snippet || "")}</div>
    </details>`).join("");
  return `
  <section class="qa-item rise">
    <div class="qa-q">${esc(question)}</div>
    <div class="qa-a">
      ${notFound ? `
        <div class="qa-notfound">
          <span class="mark">⊘</span>
          <div>${esc(resp.answer || "提供的公告未提及该信息，建议查看公告原文。")}
            <small>检索不到依据时不做推测——这是刻意设计，不是检索失败。</small></div>
        </div>` : `
        <div class="answer">${renderAnswer(resp.answer || "")}</div>`}
      ${cites ? `<div class="cites"><div class="cites-label">依据的公告片段</div>${cites}</div>` : ""}
    </div>
  </section>`;
}

async function initAskPage() {
  const form = document.getElementById("askForm");
  const input = document.getElementById("askInput");
  const list = document.getElementById("qaList");
  const sugg = document.getElementById("sugg");

  const SUGGESTIONS = [
    "资格复审后按什么比例确定入围面试人员？",
    "报名需要提交哪些材料？",
    "考察和体检怎么安排？",
    "岗位提供住宿吗？",
  ];
  sugg.innerHTML = SUGGESTIONS.map((q) => `<button class="chip" type="button">${esc(q)}</button>`).join("");
  sugg.addEventListener("click", (ev) => {
    const chip = ev.target.closest(".chip");
    if (!chip) return;
    input.value = chip.textContent;
    form.requestSubmit();
  });

  let busy = false;
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const q = input.value.trim();
    if (!q || busy) return;
    busy = true;
    input.value = "";
    const thinking = document.createElement("div");
    thinking.className = "thinking";
    thinking.innerHTML = `<span class="dot"></span>检索公告片段，AI 组织回答中…（需要几秒）`;
    list.prepend(thinking);
    try {
      const resp = await api("/rag/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q }),
      });
      thinking.outerHTML = qaItemHtml(q, resp);
    } catch (e) {
      thinking.outerHTML = `
      <section class="qa-item">
        <div class="qa-q">${esc(q)}</div>
        <div class="qa-a"><div class="qa-notfound"><span class="mark">!</span>
          <div>提问失败：${esc(e.message)}<small>确认后端已启动，或稍后重试。</small></div></div></div>
      </section>`;
    } finally {
      busy = false;
      input.focus();
    }
  });
  input.focus();
}

/* ---------- 投递记录页 ---------- */
const APP_STATUS = {
  SENT: { text: "已发送", cls: "sent" },
  PENDING: { text: "待发送", cls: "pending" },
  FAILED: { text: "发送失败", cls: "failed" },
};

async function initApplicationsPage() {
  const box = document.getElementById("appList");
  let apps = [];
  let jobs = [];
  try {
    [apps, jobs] = await Promise.all([
      api("/applications"),
      api("/jobs?include_expired=true&size=100"),
    ]);
  } catch (e) {
    if (e.status === 401) {
      showIdentityRequired(box, "投递记录");
      return;
    }
    box.innerHTML = `<div class="state">
      <div class="big">连不上后端接口</div><div>${esc(e.message)}</div>
      <div>本地演示请先启动：<code>uvicorn main:app --port 8000</code></div></div>`;
    return;
  }
  if (!apps.length) {
    box.innerHTML = `<div class="state">
      <div class="big">还没有投递记录</div>
      <div>去<a href="recommend.html" style="color:var(--brand)">推荐页</a>确认一条投递试试</div></div>`;
    return;
  }
  const jobById = Object.fromEntries(jobs.map((j) => [j.id, j]));
  // sent_at 落库是 UTC 朴素时间（无时区标记），补 Z 后按本地时区显示
  const fmtTime = (t) => {
    if (!t) return "—";
    const d = new Date(t.endsWith("Z") ? t : `${t}Z`);
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
  };
  box.innerHTML = apps.map((a, i) => {
    const st = APP_STATUS[(a.status || "").toUpperCase()] || { text: a.status, cls: "pending" };
    const job = jobById[a.job_id];
    return `
    <div class="app-row rise" style="animation-delay:${Math.min(i * 40, 300)}ms">
      <div class="app-main">
        <div class="app-title">${esc(job ? buildJobTitle(job) : "岗位已下架")}</div>
        <div class="app-sub">投递至 <span class="num">${esc(a.recipient_email)}</span> · <span class="num">${fmtTime(a.sent_at)}</span></div>
      </div>
      <span class="badge ${st.cls}">${st.text}</span>
      ${a.error_msg ? `<div class="app-err">${esc(a.error_msg)}</div>` : ""}
    </div>`;
  }).join("");
}

/* ---------- 我的页（体验身份） ---------- */

async function initMePage() {
  const guestArea = document.getElementById("guestArea");
  const form = document.getElementById("meForm");
  const note = document.getElementById("runNote");
  const sel = { stages: new Set(), subjects: new Set(), districts: new Set(), bianzhi: false };
  const pickers = [];
  let existingRuleId = null;
  let loadedResumeText = "";
  let uploadedResume = null;   // 本次通过上传创建的简历，提交时不再重复写入
  let mode = "paste";

  document.getElementById("startBtn").addEventListener("click", async () => {
    try { await ensureGuest(); await showForm(); }
    catch (e) { alert(`创建体验身份失败：${e.message}`); }
  });

  document.getElementById("quitBtn").addEventListener("click", () => {
    if (confirm("退出后该身份与其中的简历、规则、匹配结果都将作废，确定？")) {
      clearToken();
      location.reload();
    }
  });

  // 面板外点击时收起所有下拉
  document.addEventListener("click", (ev) => {
    if (!ev.target.closest(".picker")) pickers.forEach((p) => p.close());
  });

  /* ---- 简历：粘贴 / 上传 双入口 ---- */
  const pasteMode = document.getElementById("pasteMode");
  const uploadMode = document.getElementById("uploadMode");
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      mode = tab.dataset.mode;
      document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("on", t === tab));
      pasteMode.hidden = mode !== "paste";
      uploadMode.hidden = mode !== "upload";
    });
  });

  const dropZone = document.getElementById("dropZone");
  const fileInput = document.getElementById("fFile");
  const uploadResult = document.getElementById("uploadResult");

  async function sendFile(file) {
    if (!file) return;
    uploadResult.innerHTML = `<div class="upload-state">解析「${esc(file.name)}」…</div>`;
    const body = new FormData();
    body.append("file", file);
    try {
      const resume = await api("/resumes/upload", { method: "POST", body });
      uploadedResume = resume;
      const text = resume.structured_content?.["简历全文"] || "";
      loadedResumeText = text;
      document.getElementById("fResume").value = text;   // 同步到粘贴框，可继续手改
      uploadResult.innerHTML = `
        <div class="upload-file">
          <span class="name">✓ ${esc(resume.file_name)}</span>
          <span class="meta">已读出 <span class="num">${text.length}</span> 字</span>
          <button type="button" class="relink" id="reUpload">换一个文件</button>
        </div>`;
      document.getElementById("reUpload").addEventListener("click", () => fileInput.click());
    } catch (e) {
      uploadResult.innerHTML = `<div class="upload-state err">✕ ${esc(e.message)}</div>`;
    }
  }

  fileInput.addEventListener("change", () => sendFile(fileInput.files[0]));
  ["dragenter", "dragover"].forEach((t) => dropZone.addEventListener(t, (ev) => {
    ev.preventDefault(); dropZone.classList.add("over");
  }));
  ["dragleave", "drop"].forEach((t) => dropZone.addEventListener(t, (ev) => {
    ev.preventDefault(); dropZone.classList.remove("over");
  }));
  dropZone.addEventListener("drop", (ev) => sendFile(ev.dataTransfer?.files?.[0]));

  /* ---- 求职范围 ---- */
  function renderPicked() {
    const box = document.getElementById("pickedTags");
    const all = [
      ...[...sel.stages].map((v) => ["stages", v]),
      ...[...sel.subjects].map((v) => ["subjects", v]),
      ...[...sel.districts].map((v) => ["districts", v]),
    ];
    if (sel.bianzhi) all.push(["bianzhi", "只要带编制"]);
    box.innerHTML = all.length
      ? all.map(([k, v]) => `<span class="tag">${esc(v)}<button type="button" data-k="${k}" data-v="${esc(v)}" aria-label="移除 ${esc(v)}">✕</button></span>`).join("")
      : `<span class="none">未限定范围——将对全部在招岗位做 AI 精排</span>`;
  }

  document.getElementById("pickedTags").addEventListener("click", (ev) => {
    const btn = ev.target.closest("button");
    if (!btn) return;
    if (btn.dataset.k === "bianzhi") {
      sel.bianzhi = false;
      document.querySelector('.picker[data-key="bianzhi"] .picker-trigger')?.classList.remove("on");
    } else {
      sel[btn.dataset.k].delete(btn.dataset.v);
    }
    pickers.forEach((p) => p.paint());
    renderPicked();
  });

  async function showForm() {
    guestArea.hidden = true;
    form.hidden = false;

    // 选项以后端标准表为准，而非库中已有数据——订阅规则匹配的是将来爬到的
    // 岗位，当前没有体育岗位不代表体育老师不能表达意向。
    // 再并入数据里出现过的值，兜住爬到标准表之外学科的情况。
    const [tax, jobs] = await Promise.all([
      api("/taxonomy").catch(() => ({ subjects: [], stages: [], districts: [] })),
      api("/jobs?size=100").catch(() => []),
    ]);
    const merge = (canonical, key) => {
      const extra = [...new Set(jobs.map((j) => j[key]).filter(Boolean))]
        .filter((v) => !(canonical || []).includes(v)).sort();
      return [...(canonical || []), ...extra];
    };

    // 先回填已有规则，再建面板，这样面板初始就带上已选态
    try {
      const rules = await api("/rules");
      if (rules.length) {
        const r = rules[0];
        existingRuleId = r.id;
        (r.stages || []).forEach((v) => sel.stages.add(v));
        (r.subjects || []).forEach((v) => sel.subjects.add(v));
        (r.districts || []).forEach((v) => sel.districts.add(v));
        sel.bianzhi = Boolean(r.need_establishment);
      }
    } catch (_) { /* 新身份还没有规则 */ }

    const host = document.getElementById("pickers");
    host.innerHTML = "";
    [["stages", "学段", merge(tax.stages, "stage")],
     ["subjects", "学科", merge(tax.subjects, "subject")],
     ["districts", "区域", merge(tax.districts, "district")],
    ].forEach(([key, label, options]) => {
      pickers.push(createPicker(host, { key, label, options, selected: sel[key], onChange: renderPicked }));
    });

    // 编制是布尔项，用同样外观的开关而非下拉
    host.insertAdjacentHTML("beforeend", `
      <div class="picker" data-key="bianzhi">
        <button type="button" class="picker-trigger${sel.bianzhi ? " on" : ""}" id="fBianzhi" aria-pressed="${sel.bianzhi}">
          <span class="label">只要带编制</span>
        </button>
      </div>`);
    const bz = document.getElementById("fBianzhi");
    bz.addEventListener("click", () => {
      sel.bianzhi = !sel.bianzhi;
      bz.classList.toggle("on", sel.bianzhi);
      bz.setAttribute("aria-pressed", String(sel.bianzhi));
      renderPicked();
    });
    renderPicked();

    // 回填档案与简历
    try {
      const p = await api("/profile");
      document.getElementById("fName").value = p.real_name || "";
      document.getElementById("fEdu").value = p.education || "";
      document.getElementById("fMajor").value = p.major || "";
      document.getElementById("fSubject").value = p.subject || "";
    } catch (_) { /* 新身份还没有档案 */ }
    try {
      const resumes = await api("/resumes");
      const base = resumes.find((r) => r.is_default) || resumes[0];
      loadedResumeText = base?.structured_content?.["简历全文"] || "";
      document.getElementById("fResume").value = loadedResumeText;
    } catch (_) { /* 忽略 */ }
  }

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const btn = document.getElementById("runBtn");
    btn.disabled = true;
    note.className = "run-note";
    try {
      note.textContent = "保存资料…";
      await api("/profile", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          real_name: document.getElementById("fName").value.trim() || null,
          education: document.getElementById("fEdu").value || null,
          major: document.getElementById("fMajor").value.trim() || null,
          subject: document.getElementById("fSubject").value.trim() || null,
          intent: {
            学段: [...sel.stages], 学科: [...sel.subjects],
            区域: [...sel.districts], 要求编制: sel.bianzhi,
          },
        }),
      });

      // 上传入口已经落库了，这里只处理粘贴框里的手工改动
      const resumeText = document.getElementById("fResume").value.trim();
      if (resumeText && resumeText !== loadedResumeText) {
        note.textContent = "保存简历…";
        await api("/resumes", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            file_name: uploadedResume ? `${uploadedResume.file_name}（已编辑）` : "网页粘贴简历",
            file_url: "",
            is_default: true,
            structured_content: { "简历全文": resumeText },
          }),
        });
        loadedResumeText = resumeText;
      }

      note.textContent = "保存求职范围…";
      const rule = {
        name: "我的求职规则",
        stages: sel.stages.size ? [...sel.stages] : null,
        subjects: sel.subjects.size ? [...sel.subjects] : null,
        districts: sel.districts.size ? [...sel.districts] : null,
        need_establishment: sel.bianzhi || null,
      };
      if (existingRuleId) {
        await api(`/rules/${existingRuleId}`, {
          method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(rule),
        });
      } else {
        const created = await api("/rules", {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(rule),
        });
        existingRuleId = created.id;
      }

      note.textContent = "AI 逐岗评分中…";
      const started = await api("/matches/refresh", { method: "POST" });
      // mode=sync 是队列不可用时的兜底，那种情况下结果已经在响应里了
      const stats = started.mode === "async"
        ? await pollRefresh(started.task_id, (done, total) => {
            note.textContent = total
              ? `AI 逐岗评分中… ${done}/${total} 个岗位`
              : "任务排队中…";
          })
        : started;
      note.className = "run-note ok";
      if (stats.new_matches > 0) {
        note.textContent = `完成：规则命中并新评了 ${stats.new_matches} 个岗位，正在跳转推荐页…`;
        setTimeout(() => { location.href = "recommend.html"; }, 1200);
      } else {
        note.textContent = "规则没有命中新的岗位——试着放宽学段/学科/区域，或此前已评过的岗位可直接去推荐页看。";
      }
    } catch (e) {
      note.className = "run-note err";
      note.textContent = `失败：${e.message}`;
    } finally {
      btn.disabled = false;
    }
  });

  if (getToken()) await showForm();
}

/* 轮询匹配任务进度。

   用轮询而不是 WebSocket/SSE：单实例部署、任务几十秒、用户就停在这一个页面等，
   长连接要处理重连、心跳、nginx 缓冲，换不回相应的收益。

   404 容忍几次再放弃：任务状态存在 Redis 里，重启或偶发抖动可能短暂读不到，
   一次读不到就把整个流程判失败，对用户来说是白等一场。 */
async function pollRefresh(taskId, onProgress) {
  const deadline = Date.now() + 10 * 60 * 1000;
  let misses = 0;
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 1200));
    let s;
    try {
      s = await api(`/matches/refresh/${encodeURIComponent(taskId)}`);
    } catch (e) {
      if (e.status === 404 && ++misses <= 5) continue;
      throw e;
    }
    misses = 0;
    onProgress(s.done || 0, s.total || 0);
    if (s.status === "done") return s;
    if (s.status === "failed") throw new Error(s.error || "匹配任务执行失败");
  }
  throw new Error("匹配任务超时。它可能仍在后台跑，稍后到推荐页看看");
}

/* ---------- 岗位详情页 ---------- */
async function initJobDetailPage() {
  const box = document.getElementById("detail");
  const id = new URLSearchParams(location.search).get("id");
  if (!id) {
    box.innerHTML = `<div class="state"><div class="big">缺少岗位编号</div>
      <div>请从<a class="cta-inline" href="index.html">岗位列表</a>点击进入</div></div>`;
    return;
  }

  let job;
  try {
    job = await api(`/jobs/${encodeURIComponent(id)}`);
  } catch (e) {
    box.innerHTML = `<div class="state">
      <div class="big">${e.status === 404 ? "这个岗位不存在或已下架" : "加载失败"}</div>
      <div>${esc(e.message)}</div>
      <div><a class="cta-inline" href="index.html">返回岗位列表</a></div></div>`;
    return;
  }

  document.title = `${buildJobTitle(job)} · 深圳教师求职助手`;
  const dl = deadlineInfo(job.deadline);
  const expired = dl.cls === "over";
  // 只渲染有值的事实项：公告普遍缺字段，全部占位会让网格出现大片"未注明"，
  // 反而淹没真正有用的信息。缺什么在正文里看，正文永远给出链接。
  const fact = (k, v) => (v
    ? `<div class="fact"><div class="k">${k}</div><div class="v">${esc(v)}</div></div>`
    : "");

  box.innerHTML = `
    <section class="detail-head rise">
      <h1 class="detail-title">${esc(buildJobTitle(job))}</h1>
      <div class="detail-sub">
        ${job.is_establishment ? '<span class="tag-bianzhi">有编制</span>' : ""}
        <span class="salary ${job.salary_min || job.salary_max ? "" : "na"}">${esc(fmtSalary(job.salary_min, job.salary_max))}</span>
        <span class="deadline ${dl.cls}">${dl.text}</span>
      </div>
      <div class="detail-facts">
        ${fact("学校", job.school_name)}
        ${fact("区域", job.district)}
        ${fact("学段", job.stage)}
        ${fact("学科", job.subject)}
        ${fact("办学类型", job.school_type ? schoolTypeZh(job.school_type) : null)}
        ${fact("投递邮箱", job.recruiter_email)}
      </div>
      <div class="detail-actions">
        ${expired
          ? `<button class="btn btn-ghost" disabled>已过截止日期</button>
             <span class="action-note">系统会拦截已截止岗位的投递</span>`
          : !job.recruiter_email
            // 没抓到邮箱就发不出去。这里直接说明并给出官方渠道，
            // 不要放一个点进去才被拦的按钮。
            ? `<a class="btn btn-ghost" href="${esc(job.source_url || "#")}" target="_blank" rel="noopener">按公告渠道投递 ↗</a>
               <span class="action-note">这条公告没有留邮箱，请按原文指引投递</span>`
            : `<a class="btn btn-primary" href="apply.html?job=${encodeURIComponent(job.id)}">投递这个岗位</a>
               <span class="action-note">下一步可挑选简历、确认邮件主题</span>`}
      </div>
    </section>

    <section class="jd rise" style="animation-delay:80ms">
      <h2>公告正文</h2>
      ${job.description
        ? `<div class="body">${esc(job.description)}</div>`
        : `<div class="none">这条岗位没有抓到正文，请点下方链接看原始公告。</div>`}
      ${job.source_url
        ? `<div class="origin">信息来自公开招聘公告，以原文为准 ·
             <a class="cta-inline" href="${esc(job.source_url)}" target="_blank" rel="noopener">查看公告原文 ↗</a></div>`
        : ""}
    </section>`;
}

/* ---------- 投递确认页 ---------- */
async function initApplyPage() {
  const box = document.getElementById("applyBox");
  const params = new URLSearchParams(location.search);
  const jobId = params.get("job");
  const matchId = params.get("match");   // 从推荐页进来时带上，投递后该匹配转 confirmed

  document.getElementById("backLink").href =
    matchId ? "recommend.html" : (jobId ? `job.html?id=${encodeURIComponent(jobId)}` : "index.html");

  if (!jobId) {
    box.innerHTML = `<div class="state"><div class="big">缺少岗位编号</div>
      <div>请从<a class="cta-inline" href="index.html">岗位列表</a>选一个岗位再投递</div></div>`;
    return;
  }

  let job, resumes = [], templates = [];
  try {
    [job, resumes, templates] = await Promise.all([
      api(`/jobs/${encodeURIComponent(jobId)}`),
      api("/resumes").catch(() => []),
      api("/templates").catch(() => []),
    ]);
  } catch (e) {
    if (e.status === 401) { showIdentityRequired(box, "投递"); return; }
    box.innerHTML = `<div class="state"><div class="big">加载失败</div>
      <div>${esc(e.message)}</div></div>`;
    return;
  }

  const dl = deadlineInfo(job.deadline);
  const expired = dl.cls === "over";
  const noEmail = !job.recruiter_email;
  const defaultResume = resumes.find((r) => r.is_default) || resumes[0];

  // 与后端 _send_one 的默认主题保持一致，用户可改
  const defaultSubject = `应聘${job.school_name}教师岗位`;

  const blocker = expired
    ? "这个岗位已过截止日期，不能再投递。"
    : noEmail
      ? "这条公告没有抓到投递邮箱，请点开公告原文按官方渠道投递。"
      : resumes.length === 0
        ? "还没有简历。请先去「我的」页上传或粘贴一份，再回来投递。"
        : null;

  box.innerHTML = `
    <section class="apply-job">
      <div class="t">${esc(buildJobTitle(job))}</div>
      <div class="s">
        ${job.is_establishment ? '<span class="tag-bianzhi">有编制</span>' : ""}
        ${job.district ? `<span class="meta-tag">${esc(job.district)}</span>` : ""}
        <span class="deadline ${dl.cls}">${dl.text}</span>
      </div>
      <div class="to">投递至 <span class="mail">${esc(job.recruiter_email || "公告未提供邮箱")}</span></div>
    </section>

    ${blocker ? `
      <div class="apply-warn"><span>⚠</span><div>${esc(blocker)}
        ${resumes.length === 0 && !expired && !noEmail
          ? ' <a class="cta-inline" href="me.html">去上传简历 →</a>' : ""}
        ${job.source_url
          ? ` <a class="cta-inline" href="${esc(job.source_url)}" target="_blank" rel="noopener">查看公告原文 ↗</a>` : ""}
      </div></div>` : `
      <div class="card">
        <h2>选择简历</h2>
        <div class="desc">发出的附件就是这一份</div>
        <div class="pick-list" id="resumePick">
          ${resumes.map((r, i) => `
            <label class="pick-row${(defaultResume && r.id === defaultResume.id) ? " on" : ""}">
              <input type="radio" name="resume" value="${esc(r.id)}"
                ${(defaultResume && r.id === defaultResume.id) ? "checked" : ""}>
              <span class="name">${esc(r.file_name)}</span>
              <span class="meta">${r.is_default ? "默认" : ""}</span>
            </label>`).join("")}
        </div>
      </div>

      ${templates.length ? `
      <div class="card">
        <h2>求职信模板</h2>
        <div class="desc">可不选，不选则只发简历附件</div>
        <div class="pick-list" id="tplPick">
          <label class="pick-row on">
            <input type="radio" name="tpl" value="" checked>
            <span class="name">不使用模板</span>
          </label>
          ${templates.map((t) => `
            <label class="pick-row">
              <input type="radio" name="tpl" value="${esc(t.id)}">
              <span class="name">${esc(t.title)}</span>
            </label>`).join("")}
        </div>
      </div>` : ""}

      <div class="card">
        <h2>邮件主题</h2>
        <div class="desc">收件人一眼看到的就是这句</div>
        <div class="field full">
          <input id="subject" type="text" value="${esc(defaultSubject)}" maxlength="80">
        </div>
      </div>

      <div class="run-bar">
        <button class="btn btn-grad" id="sendBtn">确认发送</button>
        <span class="run-note" id="sendNote">点击后才会发出，这一步不可撤销</span>
      </div>`}
  `;

  // 单选行的视觉选中态
  box.addEventListener("change", (ev) => {
    const input = ev.target.closest('input[type="radio"]');
    if (!input) return;
    box.querySelectorAll(`input[name="${input.name}"]`).forEach((el) => {
      el.closest(".pick-row").classList.toggle("on", el.checked);
    });
  });

  const sendBtn = document.getElementById("sendBtn");
  if (!sendBtn) return;

  sendBtn.addEventListener("click", async () => {
    const note = document.getElementById("sendNote");
    // 二次确认：投递不可撤销，不能一键就发出去
    if (sendBtn.dataset.armed !== "1") {
      sendBtn.dataset.armed = "1";
      sendBtn.textContent = "确认无误，立即发送";
      note.textContent = "再点一次就会真的发出";
      return;
    }
    sendBtn.disabled = true;
    note.className = "run-note";
    note.textContent = "发送中…";
    try {
      const body = {
        job_id: jobId,
        resume_id: box.querySelector('input[name="resume"]:checked')?.value || null,
        template_id: box.querySelector('input[name="tpl"]:checked')?.value || null,
        email_subject: document.getElementById("subject").value.trim() || null,
      };
      if (matchId) body.match_id = matchId;
      const app = await api("/applications", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      box.innerHTML = `
        <div class="apply-done">
          <div class="t">✓ 已投递</div>
          <div class="s">发送至 <span class="num">${esc(app.recipient_email)}</span>
            ${app.status === "SENT" ? "" : "（状态：" + esc(app.status) + "）"}</div>
          <div class="acts">
            <a class="btn btn-primary" href="applications.html">查看投递记录</a>
            <a class="btn btn-ghost" href="index.html">继续找岗位</a>
          </div>
        </div>`;
    } catch (e) {
      sendBtn.disabled = false;
      sendBtn.dataset.armed = "";
      sendBtn.textContent = "确认发送";
      note.className = "run-note err";
      note.textContent = e.message;
    }
  });
}

/* ---------- 订阅规则管理 ---------- */
async function initRulesPage() {
  const box = document.getElementById("rulesBox");
  let rules = [], tax = {}, jobs = [];

  async function load() {
    [rules, tax, jobs] = await Promise.all([
      api("/rules"),
      api("/taxonomy").catch(() => ({ subjects: [], stages: [], districts: [] })),
      api("/jobs?size=100").catch(() => []),
    ]);
  }

  try {
    await load();
  } catch (e) {
    if (e.status === 401) { showIdentityRequired(box, "订阅规则"); return; }
    box.innerHTML = `<div class="state"><div class="big">加载失败</div>
      <div>${esc(e.message)}</div></div>`;
    return;
  }

  // 选项以标准表为准，再并入数据中出现过的值——与「我的」页同一套语义：
  // 规则要匹配的是将来爬到的岗位，不能被当前数据裁剪掉。
  const merge = (canonical, key) => {
    const extra = [...new Set(jobs.map((j) => j[key]).filter(Boolean))]
      .filter((v) => !(canonical || []).includes(v)).sort();
    return [...(canonical || []), ...extra];
  };
  const OPTIONS = {
    stages: merge(tax.stages, "stage"),
    subjects: merge(tax.subjects, "subject"),
    districts: merge(tax.districts, "district"),
  };

  const condTags = (r) => {
    const all = [...(r.stages || []), ...(r.subjects || []), ...(r.districts || [])];
    if (r.need_establishment) all.push("只要带编制");
    return all.length
      ? all.map((v) => `<span class="meta-tag">${esc(v)}</span>`).join("")
      : `<span class="none">未限定条件——将对全部在招岗位做 AI 精排</span>`;
  };

  function render() {
    box.innerHTML = `
      ${rules.length ? rules.map((r) => `
        <section class="rule-card${r.is_active ? "" : " off"}" data-id="${esc(r.id)}">
          <div class="rule-head">
            <span class="rule-name">${esc(r.name || "未命名规则")}</span>
            <span class="rule-badge ${r.is_active ? "on" : "off"}">${r.is_active ? "启用中" : "已停用"}</span>
            <span class="rule-acts">
              <button type="button" class="act-toggle">${r.is_active ? "停用" : "启用"}</button>
              <button type="button" class="act-edit">编辑</button>
              <button type="button" class="act-del del">删除</button>
            </span>
          </div>
          <div class="rule-cond">${condTags(r)}</div>
        </section>`).join("") : `
        <div class="state">
          <div class="big">还没有订阅规则</div>
          <div>建一条规则，AI 只会对命中的岗位打分——这是成本控制的第一道闸</div>
        </div>`}

      <div class="run-bar" style="margin-top:16px">
        <button class="btn btn-grad" id="addRule">新建规则</button>
        <a class="btn btn-ghost" href="me.html">回「我的」跑匹配</a>
      </div>`;
  }

  /* 展开编辑表单。rule 为空时是新建。 */
  function openForm(card, rule) {
    const sel = {
      stages: new Set(rule?.stages || []),
      subjects: new Set(rule?.subjects || []),
      districts: new Set(rule?.districts || []),
      bianzhi: Boolean(rule?.need_establishment),
    };
    card.insertAdjacentHTML("beforeend", `
      <div class="rule-form">
        <div class="field full" style="margin-bottom:12px">
          <label>规则名称</label>
          <input class="rule-name-input" value="${esc(rule?.name || "")}" placeholder="比如：南山区小学语文" maxlength="40">
        </div>
        <div class="pickers"></div>
        <div class="picked"></div>
        <div class="run-bar" style="margin-top:14px">
          <button class="btn btn-primary act-save">${rule ? "保存修改" : "创建规则"}</button>
          <button class="btn btn-ghost act-cancel">取消</button>
          <span class="run-note"></span>
        </div>
      </div>`);

    const form = card.querySelector(".rule-form");
    const host = form.querySelector(".pickers");
    const pickedBox = form.querySelector(".picked");
    const pickers = [];

    const renderPicked = () => {
      const all = [
        ...[...sel.stages].map((v) => ["stages", v]),
        ...[...sel.subjects].map((v) => ["subjects", v]),
        ...[...sel.districts].map((v) => ["districts", v]),
      ];
      if (sel.bianzhi) all.push(["bianzhi", "只要带编制"]);
      pickedBox.innerHTML = all.length
        ? all.map(([k, v]) => `<span class="tag">${esc(v)}<button type="button" data-k="${k}" data-v="${esc(v)}" aria-label="移除 ${esc(v)}">✕</button></span>`).join("")
        : `<span class="none">未限定范围——将对全部在招岗位做 AI 精排</span>`;
    };

    [["stages", "学段"], ["subjects", "学科"], ["districts", "区域"]].forEach(([key, label]) => {
      pickers.push(createPicker(host, {
        key, label, options: OPTIONS[key], selected: sel[key], onChange: renderPicked,
      }));
    });
    host.insertAdjacentHTML("beforeend", `
      <div class="picker" data-key="bianzhi">
        <button type="button" class="picker-trigger bz${sel.bianzhi ? " on" : ""}" aria-pressed="${sel.bianzhi}">
          <span class="label">只要带编制</span>
        </button>
      </div>`);
    const bz = host.querySelector(".bz");
    bz.addEventListener("click", () => {
      sel.bianzhi = !sel.bianzhi;
      bz.classList.toggle("on", sel.bianzhi);
      bz.setAttribute("aria-pressed", String(sel.bianzhi));
      renderPicked();
    });
    pickedBox.addEventListener("click", (ev) => {
      const btn = ev.target.closest("button");
      if (!btn) return;
      if (btn.dataset.k === "bianzhi") { sel.bianzhi = false; bz.classList.remove("on"); }
      else sel[btn.dataset.k].delete(btn.dataset.v);
      pickers.forEach((p) => p.paint());
      renderPicked();
    });
    renderPicked();

    form.querySelector(".act-cancel").addEventListener("click", render);
    form.querySelector(".act-save").addEventListener("click", async () => {
      const note = form.querySelector(".run-note");
      const name = form.querySelector(".rule-name-input").value.trim();
      if (!name) { note.className = "run-note err"; note.textContent = "请先给规则起个名字"; return; }
      note.className = "run-note"; note.textContent = "保存中…";
      const body = {
        name,
        stages: sel.stages.size ? [...sel.stages] : null,
        subjects: sel.subjects.size ? [...sel.subjects] : null,
        districts: sel.districts.size ? [...sel.districts] : null,
        need_establishment: sel.bianzhi || null,
        is_active: rule ? rule.is_active : true,
      };
      try {
        await api(rule ? `/rules/${rule.id}` : "/rules", {
          method: rule ? "PUT" : "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        await load();
        render();
      } catch (e) {
        note.className = "run-note err";
        note.textContent = e.message;
      }
    });
  }

  box.addEventListener("click", async (ev) => {
    if (ev.target.id === "addRule") {
      box.insertAdjacentHTML("afterbegin", '<section class="rule-card" data-new="1"></section>');
      openForm(box.firstElementChild, null);
      return;
    }
    const card = ev.target.closest(".rule-card");
    if (!card) return;
    const rule = rules.find((r) => r.id === card.dataset.id);
    if (!rule) return;

    if (ev.target.closest(".act-edit")) {
      if (!card.querySelector(".rule-form")) openForm(card, rule);
      return;
    }
    if (ev.target.closest(".act-toggle")) {
      // 停用而非删除：规则停了，历史匹配结果仍保留
      await api(`/rules/${rule.id}`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...rule, is_active: !rule.is_active }),
      });
      await load(); render();
      return;
    }
    if (ev.target.closest(".act-del")) {
      if (!confirm(`删除规则「${rule.name}」？该规则命中的历史匹配结果也会一并删除。`)) return;
      await api(`/rules/${rule.id}`, { method: "DELETE" });
      await load(); render();
    }
  });

  render();
}
