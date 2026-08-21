/**
 * 配置页。API Key 只写入不回显：读出来是空的就是「不改」，
 * 免得把已存的 Key 渲染到 DOM 上。
 */

import { DEFAULT_PROFILE, normalizeProfile } from '../domain/profile.js';

const $ = (id) => document.getElementById(id);

const TEXT_FIELDS = ['city'];
const NUM_FIELDS = ['salaryMinK', 'salaryIdealK', 'maxRequiredYears', 'applyThreshold', 'reviewThreshold'];
const LIST_FIELDS = ['targetKeywords', 'blocklist', 'skills', 'preferredCompanySizes', 'preferredPublisherTitles'];

function send(type, payload) {
  return new Promise((resolve) => chrome.runtime.sendMessage({ type, payload }, resolve));
}

function status(text, isError = false) {
  const el = $('status');
  el.textContent = text;
  el.className = isError ? 'status err' : 'status';
  if (text) setTimeout(() => (el.textContent = ''), 4000);
}

function fillProfile(profile) {
  for (const f of TEXT_FIELDS) $(f).value = profile[f] ?? '';
  for (const f of NUM_FIELDS) $(f).value = profile[f] ?? '';
  for (const f of LIST_FIELDS) $(f).value = (profile[f] || []).join('\n');
  $('educationLevel').value = profile.educationLevel || 'bachelor';
  $('facts').value = JSON.stringify(profile.facts || [], null, 2);

  const pref = profile.preference || {};
  $('preferenceEnabled').checked = Boolean(pref.enabled);
  $('preferencePositives').value = (pref.positives || []).join('\n');
  $('preferenceNegatives').value = (pref.negatives || []).join('\n');
  $('preferencePerItem').value = pref.perItem ?? 10;
  $('preferenceMinScore').value = pref.minScore ?? 0;
}

const lines = (id) =>
  $(id)
    .value.split('\n')
    .map((s) => s.trim())
    .filter(Boolean);

function readProfile() {
  const profile = {};
  for (const f of TEXT_FIELDS) profile[f] = $(f).value.trim();
  for (const f of NUM_FIELDS) profile[f] = Number($(f).value);
  for (const f of LIST_FIELDS) {
    profile[f] = $(f)
      .value.split('\n')
      .map((s) => s.trim())
      .filter(Boolean);
  }
  profile.educationLevel = $('educationLevel').value;
  profile.preference = {
    enabled: $('preferenceEnabled').checked,
    positives: lines('preferencePositives'),
    negatives: lines('preferenceNegatives'),
    perItem: Number($('preferencePerItem').value),
    minScore: Number($('preferenceMinScore').value)
  };

  const factsRaw = $('facts').value.trim();
  if (factsRaw) {
    let parsed;
    try {
      parsed = JSON.parse(factsRaw);
    } catch (e) {
      throw new Error(`事实库不是合法 JSON：${e.message}`);
    }
    if (!Array.isArray(parsed)) throw new Error('事实库必须是数组');
    profile.facts = parsed;
  }
  return normalizeProfile(profile);
}

function fillApi(apiConfig) {
  $('llmBaseUrl').value = apiConfig.llmBaseUrl || '';
  $('llmModel').value = apiConfig.llmModel || '';
  $('dailyLlmLimit').value = apiConfig.dailyLlmLimit ?? 60;
  $('searchProvider').value = apiConfig.searchProvider || 'tavily';
  $('enableLlm').checked = Boolean(apiConfig.enableLlm);
  $('enableSearch').checked = Boolean(apiConfig.enableSearch);
  $('llmApiKey').placeholder = apiConfig.hasLlmKey ? '已保存，留空表示不改' : '未配置';
  $('searchApiKey').placeholder = apiConfig.hasSearchKey ? '已保存，留空表示不改' : '未配置';
}

function readApi() {
  const api = {
    llmBaseUrl: $('llmBaseUrl').value.trim(),
    llmModel: $('llmModel').value.trim(),
    dailyLlmLimit: Number($('dailyLlmLimit').value) || 0,
    searchProvider: $('searchProvider').value,
    enableLlm: $('enableLlm').checked,
    enableSearch: $('enableSearch').checked
  };
  // 空字符串表示不改，不要把已存的 Key 覆盖掉
  const llmKey = $('llmApiKey').value.trim();
  const searchKey = $('searchApiKey').value.trim();
  if (llmKey) api.llmApiKey = llmKey;
  if (searchKey) api.searchApiKey = searchKey;
  return api;
}

function fillSend(sendConfig) {
  $('fillOnly').checked = Boolean(sendConfig.fillOnly);
  $('autoSend').checked = Boolean(sendConfig.autoSend);
  $('allowReviewSend').checked = Boolean(sendConfig.allowReviewSend);
  $('dailySendLimit').value = sendConfig.dailySendLimit ?? 30;
  const [start, end] = sendConfig.workingHours || [9, 22];
  $('hourStart').value = start;
  $('hourEnd').value = end;
  refreshSendWarning();
}

function readSend() {
  const start = Number($('hourStart').value);
  const end = Number($('hourEnd').value);
  return {
    fillOnly: $('fillOnly').checked,
    autoSend: $('autoSend').checked,
    allowReviewSend: $('allowReviewSend').checked,
    dailySendLimit: Number($('dailySendLimit').value) || 0,
    workingHours: [Number.isFinite(start) ? start : 9, Number.isFinite(end) ? end : 22]
  };
}

/** 把当前组合会产生什么后果直说，别让人靠猜。 */
function refreshSendWarning() {
  const el = $('sendWarning');
  const fillOnly = $('fillOnly').checked;
  const autoSend = $('autoSend').checked;
  const review = $('allowReviewSend').checked;

  if (fillOnly || !autoSend) {
    el.textContent = '当前：只把招呼语填进输入框，发送键你自己按。';
    el.className = 'sub';
    return;
  }
  el.textContent = review
    ? '当前：绿灯和黄灯岗位都会自动点发送。黄灯本来就是「没把握」，这个组合最容易发错。'
    : '当前：绿灯岗位会自动点发送，你不需要点任何东西。账号风险由你承担。';
  el.className = 'sub';
  el.style.color = 'var(--red)';
}

for (const id of ['fillOnly', 'autoSend', 'allowReviewSend']) {
  $(id).addEventListener('change', () => {
    // 只填不发 和 自动发送 是互斥的，勾一个就把另一个放下
    if (id === 'fillOnly' && $('fillOnly').checked) $('autoSend').checked = false;
    if (id === 'autoSend' && $('autoSend').checked) $('fillOnly').checked = false;
    refreshSendWarning();
  });
}

async function load() {
  const res = await send('GET_STATE');
  if (!res?.ok) {
    status('读取配置失败', true);
    return;
  }
  fillProfile(res.data.profile);
  fillApi(res.data.apiConfig);
  fillSend(res.data.sendConfig || {});
}

$('save').addEventListener('click', async () => {
  let profile;
  try {
    profile = readProfile();
  } catch (e) {
    status(e.message, true);
    return;
  }
  const a = await send('SAVE_PROFILE', { profile });
  const b = await send('SAVE_API_CONFIG', { apiConfig: readApi() });
  const c = await send('SAVE_SEND_CONFIG', { sendConfig: readSend() });
  if (a?.ok && b?.ok && c?.ok) {
    $('llmApiKey').value = '';
    $('searchApiKey').value = '';
    await load();
    status('已保存。画像变了，旧的评估缓存已作废。');
  } else {
    status(a?.error || b?.error || c?.error || '保存失败', true);
  }
});

$('reset').addEventListener('click', () => {
  fillProfile(DEFAULT_PROFILE);
  status('已填回默认画像，记得点保存');
});

$('export').addEventListener('click', async () => {
  const res = await send('EXPORT_ALL');
  if (!res?.ok) {
    status('导出失败', true);
    return;
  }
  const blob = new Blob([JSON.stringify(res.data.data, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `boss-assistant-${new Date().toISOString().slice(0, 10)}.json`;
  a.click();
  URL.revokeObjectURL(url);
  status('已导出（不含 API Key）');
});

$('clear').addEventListener('click', async () => {
  if (!confirm('清空全部本地数据（画像、Key、评估记录）？不可恢复。')) return;
  const res = await send('CLEAR_ALL');
  if (res?.ok) {
    await load();
    status('已清空');
  } else {
    status('清空失败', true);
  }
});

load();
