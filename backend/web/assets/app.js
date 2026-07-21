/* 教师求职 Demo · 共享脚本
   同源部署（FastAPI StaticFiles 挂载），fetch 直接打相对路径，无 CORS。 */

/* 体验身份令牌：存在则所有请求自动携带；不存在时后端(dev 模式)回退 demo 用户 */
const TOKEN_KEY = "tjf_guest_token";
const getToken = () => localStorage.getItem(TOKEN_KEY);
const clearToken = () => localStorage.removeItem(TOKEN_KEY);

const api = async (path, options = {}) => {
  const headers = { ...(options.headers || {}) };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const resp = await fetch(path, { ...options, headers });
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try { detail = (await resp.json()).detail || detail; } catch (_) { /* 非 JSON 响应 */ }
    throw new Error(detail);
  }
  return resp.json();
};

async function ensureGuest() {
  if (getToken()) return getToken();
  const d = await api("/auth/guest", { method: "POST" });
  localStorage.setItem(TOKEN_KEY, d.token);
  return d.token;
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

/* ---------- 岗位页 ---------- */
async function initJobsPage() {
  const grid = document.getElementById("grid");
  const statsEl = document.getElementById("stats");
  const filtersEl = document.getElementById("filters");
  let jobs = [];
  const active = { district: null, stage: null, bianzhi: false };

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

  const chipRow = (label, key, values) => `
    <div class="chip-row" data-key="${key}">
      <span class="label">${label}</span>
      <button class="chip on" data-v="">全部</button>
      ${values.map((v) => `<button class="chip" data-v="${esc(v)}">${esc(v)}<span class="n num">${count(key, v)}</span></button>`).join("")}
    </div>`;

  filtersEl.innerHTML =
    chipRow("区域", "district", uniq("district").sort()) +
    chipRow("学段", "stage", uniq("stage").sort()) +
    `<div class="chip-row" data-key="bianzhi">
      <span class="label">编制</span>
      <button class="chip" data-v="1">只看带编制</button>
    </div>`;

  filtersEl.addEventListener("click", (ev) => {
    const chip = ev.target.closest(".chip");
    if (!chip) return;
    const row = chip.closest(".chip-row");
    const key = row.dataset.key;
    if (key === "bianzhi") {
      active.bianzhi = !active.bianzhi;
      chip.classList.toggle("on", active.bianzhi);
    } else {
      row.querySelectorAll(".chip").forEach((c) => c.classList.remove("on"));
      chip.classList.add("on");
      active[key] = chip.dataset.v || null;
    }
    render();
  });

  function render() {
    const list = jobs.filter((j) =>
      (!active.district || j.district === active.district) &&
      (!active.stage || j.stage === active.stage) &&
      (!active.bianzhi || j.is_establishment));
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
          <h3 class="job-title">${esc(buildJobTitle(j))}</h3>
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
        ${j.source_url ? `<div class="job-link"><a href="${esc(j.source_url)}" target="_blank" rel="noopener">查看公告原文 ↗</a></div>` : ""}
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

async function initRecommendPage() {
  const box = document.getElementById("matches");
  let items = [];
  try {
    items = await api("/recommendations");
  } catch (e) {
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
        <div class="remark">
          <span class="eyebrow">✦ AI 匹配评语</span>
          <div>${esc(reason)}</div>
        </div>
        ${m.cover_letter ? `
        <details class="cover">
          <summary>AI 起草的求职信</summary>
          <div class="cover-body">${esc(m.cover_letter)}</div>
        </details>` : ""}
        <div class="match-actions">
          ${confirmed
            ? '<button class="btn btn-done">已确认投递</button>'
            : `<button class="btn btn-primary act-apply">确认投递</button>
               <button class="btn btn-ghost act-cancel" hidden>取消</button>`}
          <span class="action-note">${confirmed ? "" : "投递前需你确认，系统不会自动发送"}</span>
        </div>
      </div>
    </section>`;
  }).join("");

  animateRings();

  box.addEventListener("click", async (ev) => {
    const btn = ev.target.closest(".act-apply");
    if (!btn) return;
    const card = btn.closest(".match-card");
    const note = card.querySelector(".action-note");
    if (btn.dataset.armed !== "1") {
      btn.dataset.armed = "1";
      btn.textContent = "确认发送简历？";
      card.querySelector(".act-cancel").hidden = false;
      card.querySelector(".act-cancel").onclick = () => {
        btn.dataset.armed = ""; btn.textContent = "确认投递";
        card.querySelector(".act-cancel").hidden = true; note.textContent = "投递前需你确认，系统不会自动发送"; note.classList.remove("err");
      };
      return;
    }
    btn.disabled = true; note.textContent = "发送中…"; note.classList.remove("err");
    try {
      await api("/applications", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_id: card.dataset.jid, match_id: card.dataset.mid }),
      });
      btn.className = "btn btn-done"; btn.textContent = "已确认投递"; btn.disabled = false;
      card.querySelector(".act-cancel").hidden = true;
      note.textContent = "已进入投递记录";
    } catch (e) {
      btn.disabled = false; btn.dataset.armed = ""; btn.textContent = "确认投递";
      card.querySelector(".act-cancel").hidden = true;
      note.textContent = e.message; note.classList.add("err");
    }
  });
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
  let existingRuleId = null;
  let loadedResumeText = "";

  document.getElementById("startBtn").addEventListener("click", async () => {
    try {
      await ensureGuest();
      await showForm();
    } catch (e) { alert(`创建体验身份失败：${e.message}`); }
  });

  document.getElementById("quitBtn").addEventListener("click", () => {
    if (confirm("退出后该身份与其中的简历、规则、匹配结果都将作废，确定？")) {
      clearToken();
      location.reload();
    }
  });

  document.getElementById("fBianzhi").addEventListener("click", (ev) => {
    sel.bianzhi = !sel.bianzhi;
    ev.target.classList.toggle("on", sel.bianzhi);
  });

  async function showForm() {
    guestArea.hidden = true;
    form.hidden = false;

    // 选项来自真实岗位数据，保证规则值与库里的字段能精确对上
    const jobs = await api("/jobs?size=100").catch(() => []);
    const uniq = (k) => [...new Set(jobs.map((j) => j[k]).filter(Boolean))].sort();
    const rows = [["学段", "stages", uniq("stage")], ["学科", "subjects", uniq("subject")], ["区域", "districts", uniq("district")]];
    document.getElementById("ruleChips").innerHTML = rows.map(([label, key, values]) => `
      <div class="chip-row" data-key="${key}">
        <span class="label">${label}</span>
        ${values.map((v) => `<button type="button" class="chip" data-v="${esc(v)}">${esc(v)}</button>`).join("")}
      </div>`).join("");
    document.getElementById("ruleChips").addEventListener("click", (ev) => {
      const chip = ev.target.closest(".chip");
      if (!chip) return;
      const key = chip.closest(".chip-row").dataset.key;
      const v = chip.dataset.v;
      if (sel[key].has(v)) { sel[key].delete(v); chip.classList.remove("on"); }
      else { sel[key].add(v); chip.classList.add("on"); }
    });

    // 回填已有数据（重复访问时）
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
    try {
      const rules = await api("/rules");
      if (rules.length) {
        const r = rules[0];
        existingRuleId = r.id;
        (r.stages || []).forEach((v) => sel.stages.add(v));
        (r.subjects || []).forEach((v) => sel.subjects.add(v));
        (r.districts || []).forEach((v) => sel.districts.add(v));
        sel.bianzhi = Boolean(r.need_establishment);
        document.getElementById("fBianzhi").classList.toggle("on", sel.bianzhi);
        document.querySelectorAll("#ruleChips .chip").forEach((chip) => {
          const key = chip.closest(".chip-row").dataset.key;
          if (sel[key].has(chip.dataset.v)) chip.classList.add("on");
        });
      }
    } catch (_) { /* 忽略 */ }
  }

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const btn = document.getElementById("runBtn");
    btn.disabled = true;
    note.className = "run-note";
    try {
      note.textContent = "保存资料…";
      const subject = document.getElementById("fSubject").value.trim();
      await api("/profile", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          real_name: document.getElementById("fName").value.trim() || null,
          education: document.getElementById("fEdu").value || null,
          major: document.getElementById("fMajor").value.trim() || null,
          subject: subject || null,
          intent: {
            学段: [...sel.stages], 学科: [...sel.subjects],
            区域: [...sel.districts], 要求编制: sel.bianzhi,
          },
        }),
      });

      const resumeText = document.getElementById("fResume").value.trim();
      if (resumeText && resumeText !== loadedResumeText) {
        note.textContent = "保存简历…";
        await api("/resumes", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            file_name: "网页粘贴简历",
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
          method: "PUT", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(rule),
        });
      } else {
        const created = await api("/rules", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(rule),
        });
        existingRuleId = created.id;
      }

      note.textContent = "AI 逐岗评分中…（几秒）";
      const stats = await api("/matches/refresh", { method: "POST" });
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
