/* V1 原生前端：token 只存在此模块内存，刷新页面即丢失。 */
let token = null;
let me = null;
let selectedConversationId = null;
let currentDraft = null;

const $ = (selector) => document.querySelector(selector);

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(`/api${path}`, { ...options, headers });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || "请求失败");
  }
  return response.status === 204 ? null : response.json();
}

function escapeHtml(value = "") {
  return String(value).replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);
}

function time(value) { return value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : ""; }
function riskTag(draft) { return draft.risk_level === "high" ? '<span class="tag high">需人工审核</span>' : '<span class="tag low">低风险草稿</span>'; }

async function login(event) {
  event.preventDefault();
  $("#login-error").textContent = "";
  try {
    const data = await api("/auth/login", { method: "POST", body: JSON.stringify({ username: $("#username").value, password: $("#password").value }) });
    token = data.access_token;
    me = await api("/auth/me");
    $("#current-user").textContent = `${me.username} · ${me.role === "admin" ? "管理员" : "客服"}`;
    $("#login-view").hidden = true;
    $("#app-view").hidden = false;
    // 仅管理员看到接入中心入口；后端对 agent 同样返回 403
    $("#tab-integrations").hidden = me.role !== "admin";
    await loadConversations();
    await loadReviews();
  } catch (err) { $("#login-error").textContent = err.message; }
}

async function loadConversations() {
  const conversations = await api("/conversations");
  $("#conversation-list").innerHTML = conversations.map((c) => `<button class="conversation ${c.id === selectedConversationId ? "selected" : ""}" data-id="${c.id}"><b>${escapeHtml(c.buyer_name)}</b><span>${c.order ? escapeHtml(c.order.order_no) : "无关联订单"} · ${escapeHtml(c.lang)}</span></button>`).join("");
  $("#conversation-list").querySelectorAll("button").forEach((button) => button.addEventListener("click", () => selectConversation(Number(button.dataset.id))));
  if (!selectedConversationId && conversations.length) await selectConversation(conversations[0].id);
}

function renderOrder(order) {
  if (!order) return "<p>此会话未关联演示订单。</p>";
  const steps = (order.logistics_steps || []).map((step) => `<li>${escapeHtml(step)}</li>`).join("");
  return `<dl><dt>订单</dt><dd>${escapeHtml(order.order_no)}（演示）</dd><dt>平台</dt><dd>${escapeHtml(order.platform)}</dd><dt>状态</dt><dd>${escapeHtml(order.status)}</dd><dt>物流</dt><dd>${escapeHtml(order.shipping_summary || "暂无")}</dd></dl>${steps ? `<ol>${steps}</ol>` : ""}`;
}

function renderDraft(draft, citations = []) {
  currentDraft = draft;
  const citationHtml = citations.length ? `<h3>引用来源</h3><ul>${citations.map((article) => `<li><b>${escapeHtml(article.title)}</b><br>${escapeHtml(article.body)}</li>`).join("")}</ul>` : "<p class=\"muted\">未命中店铺政策：草稿仅请求人工确认，不作政策承诺。</p>";
  const accept = draft.status === "pending_agent" ? `<button id="accept-draft">采纳为待发送记录</button>` : "";
  $("#draft-panel").innerHTML = `<article class="draft"><div>${riskTag(draft)} <span class="muted">${escapeHtml(draft.generator)}</span></div><p>${escapeHtml(draft.body)}</p><small>状态：${escapeHtml(draft.status)}。V1 不对接外部消息平台，系统不会发送。</small>${accept}${citationHtml}</article>`;
  const acceptButton = $("#accept-draft");
  if (acceptButton) acceptButton.addEventListener("click", acceptDraft);
}

async function selectConversation(id) {
  selectedConversationId = id;
  const detail = await api(`/conversations/${id}`);
  $("#conversation-header").innerHTML = `<p class="eyebrow">演示会话 · ${escapeHtml(detail.conversation.lang)}</p><h2>${escapeHtml(detail.conversation.buyer_name)}</h2>`;
  $("#messages").innerHTML = detail.messages.map((message) => `<article class="message ${message.sender}"><b>${message.sender === "buyer" ? "买家" : "客服"}</b><p>${escapeHtml(message.body)}</p>${message.was_redacted ? "<small>已最小化脱敏</small>" : ""}</article>`).join("") || "<p class=\"muted\">尚无消息。可使用下方输入框演示处理流程。</p>";
  $("#order-context").innerHTML = renderOrder(detail.conversation.order);
  const draft = detail.drafts.at(-1);
  if (draft) renderDraft(draft); else { currentDraft = null; $("#draft-panel").innerHTML = "<p class=\"muted\">录入买家消息后显示 AI 草稿和引用。</p>"; }
  await loadConversations();
}

async function createMessage(event) {
  event.preventDefault();
  if (!selectedConversationId) return;
  const button = event.submitter;
  button.disabled = true;
  try {
    const response = await api(`/conversations/${selectedConversationId}/messages`, { method: "POST", body: JSON.stringify({ text: $("#buyer-message").value }) });
    $("#buyer-message").value = "";
    await selectConversation(selectedConversationId);
    renderDraft(response.draft, response.citations);
    if (response.human_review_required) alert(`该诉求已创建人工审核单（${response.risk_type}）。系统未执行任何外部操作。`);
    await loadReviews();
  } catch (err) { alert(err.message); } finally { button.disabled = false; }
}

async function acceptDraft() {
  if (!currentDraft) return;
  try {
    await api(`/conversations/${selectedConversationId}/drafts/${currentDraft.id}/accept`, { method: "POST" });
    await selectConversation(selectedConversationId);
  } catch (err) { alert(err.message); }
}

async function loadReviews() {
  const reviews = await api("/reviews");
  const pending = reviews.filter((review) => review.status === "pending").length;
  $("#review-count").textContent = pending ? `(${pending})` : "";
  $("#reviews-list").innerHTML = reviews.map((review) => {
    const actions = review.status === "pending" && me.role === "admin" ? `<form class="decision-form" data-id="${review.id}"><textarea maxlength="500" required placeholder="填写审核理由（必填）"></textarea><div><button type="submit" data-decision="approve">通过（仅记录结论）</button><button type="button" data-decision="reject" class="danger">驳回</button></div></form>` : "";
    return `<article class="review"><div><span class="tag high">${escapeHtml(review.risk_type_label)}</span> <span class="muted">${escapeHtml(review.status)}</span></div><h3>${escapeHtml(review.buyer_name)} · 会话 #${review.conversation_id}</h3><p>${escapeHtml(review.draft_body)}</p><small>创建：${time(review.created_at)}${review.reviewer ? ` · 审核人：${escapeHtml(review.reviewer)}` : ""}${review.review_reason ? ` · 理由：${escapeHtml(review.review_reason)}` : ""}</small>${actions}</article>`;
  }).join("") || "<p class=\"muted\">暂无审核单。</p>";
  $("#reviews-list").querySelectorAll(".decision-form").forEach((form) => {
    form.addEventListener("submit", (event) => decideReview(event, "approve"));
    form.querySelector(".danger").addEventListener("click", (event) => { event.preventDefault(); decideReview({ currentTarget: form, preventDefault() {} }, "reject"); });
  });
}

async function decideReview(event, decision) {
  event.preventDefault();
  const form = event.currentTarget;
  const reason = form.querySelector("textarea").value;
  try { await api(`/reviews/${form.dataset.id}/${decision}`, { method: "POST", body: JSON.stringify({ reason }) }); await loadReviews(); }
  catch (err) { alert(err.message); }
}

/* ── 接入中心（演示）───────────────────────────────────────────────
 * 只管理"接入配置草稿"：不连真实店铺、不收凭证、不发外部请求。
 * 页面里刻意没有 API Key / Token / Secret 的任何输入框——
 * 后端也不接收这些字段，前端多给一个框只会诱导用户往里粘真凭证。
 * 也不写 localStorage：token 与草稿都只活在内存里，刷新即清。
 */
const PROVIDER_LABEL = { shopify: "Shopify", amazon: "Amazon", tiktok_shop: "TikTok Shop" };
const MODE_LABEL = { manual: "手动配置", guided: "引导配置" };

async function loadIntegrations() {
  const list = $("#integration-list");
  try {
    const rows = await api("/integrations");
    list.innerHTML = rows.map((row) => `<article class="review">
      <div><span class="tag low">草稿</span> <span class="muted">${escapeHtml(MODE_LABEL[row.mode] || row.mode)}</span></div>
      <h3>${escapeHtml(PROVIDER_LABEL[row.provider] || row.provider)} · ${escapeHtml(row.store_identifier)}</h3>
      <small class="muted">区域：${escapeHtml(row.region)}　权限范围：${row.requested_scopes.length ? escapeHtml(row.requested_scopes.join("、")) : "（未填写）"}</small>
      <small>创建：${time(row.created_at)}</small>
      <div><button type="button" class="danger" data-delete="${row.id}">删除草稿</button></div>
    </article>`).join("") || '<p class="muted">暂无接入草稿。</p>';
    list.querySelectorAll("[data-delete]").forEach((button) => {
      button.addEventListener("click", async () => {
        try { await api(`/integrations/${button.dataset.delete}`, { method: "DELETE" }); await loadIntegrations(); }
        catch (err) { $("#integration-error").textContent = err.message; }
      });
    });
  } catch (err) {
    // 403 走这里：agent 即使拿到入口也看不到数据，后端才是权限边界
    list.innerHTML = `<p class="error">${escapeHtml(err.message)}（接入中心仅管理员可访问）</p>`;
  }
}

async function createIntegration(event) {
  event.preventDefault();
  $("#integration-error").textContent = "";
  const scopes = $("#int-scopes").value.split(",").map((s) => s.trim()).filter(Boolean);
  try {
    await api("/integrations", { method: "POST", body: JSON.stringify({
      provider: $("#int-provider").value,
      mode: "manual",
      store_identifier: $("#int-store").value.trim(),
      region: $("#int-region").value.trim(),
      requested_scopes: scopes,
    }) });
    $("#integration-form").reset();
    await loadIntegrations();
  } catch (err) { $("#integration-error").textContent = err.message; }
}

async function loadBlueprint() {
  const panel = $("#blueprint-panel");
  try {
    const bp = await api(`/integrations/providers/${$("#blueprint-provider").value}/blueprint`);
    panel.innerHTML = `<div class="blueprint">
      <p class="muted">认证方式：<strong>${escapeHtml(bp.auth_type)}</strong></p>
      <h4>所需权限范围</h4><ul>${bp.required_scopes.map((x) => `<li><code>${escapeHtml(x)}</code></li>`).join("")}</ul>
      <h4>V2 预留回调路径（当前未启用）</h4><p><code>${escapeHtml(bp.webhook_callback_path)}</code></p>
      <h4>环境变量名（值请配置在部署环境，勿填入本页）</h4>
      <ul>${bp.env_var_names.map((x) => `<li><code>${escapeHtml(x)}</code></li>`).join("")}</ul>
      <h4>后续步骤</h4><ol>${bp.next_steps.map((x) => `<li>${escapeHtml(x)}</li>`).join("")}</ol>
      <p class="notice">${escapeHtml(bp.notice)}</p>
    </div>`;
  } catch (err) {
    panel.innerHTML = `<p class="error">${escapeHtml(err.message)}</p>`;
  }
}

document.querySelectorAll(".tabs button").forEach((button) => button.addEventListener("click", () => {
  document.querySelectorAll(".tabs button").forEach((item) => item.classList.remove("active"));
  button.classList.add("active");
  document.querySelectorAll(".view").forEach((view) => { view.hidden = view.id !== button.dataset.view; });
  if (button.dataset.view === "reviews") loadReviews();
  if (button.dataset.view === "integrations") { loadIntegrations(); loadBlueprint(); }
}));
$("#login-form").addEventListener("submit", login);
$("#message-form").addEventListener("submit", createMessage);
$("#integration-form").addEventListener("submit", createIntegration);
$("#blueprint-provider").addEventListener("change", loadBlueprint);
$("#logout").addEventListener("click", () => window.location.reload());
