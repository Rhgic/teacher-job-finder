/** 控制台。只显示用量和两个开关，没有「开始投递」这种按钮，因为它不投。 */

const $ = (id) => document.getElementById(id);

function send(type, payload) {
  return new Promise((resolve) => chrome.runtime.sendMessage({ type, payload }, resolve));
}

function todayStart() {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

async function load() {
  const [state, records] = await Promise.all([send('GET_STATE'), send('GET_RECORDS')]);
  if (!state?.ok) return;

  const usage = state.data.usage || {};
  $('evaluated').textContent = usage.evaluated || 0;
  $('llmCalls').textContent = `${usage.llmCalls || 0} / ${state.data.apiConfig.dailyLlmLimit ?? '-'}`;
  $('searchCalls').textContent = usage.searchCalls || 0;

  const today = todayStart();
  const todays = (records?.data?.records || []).filter((r) => (r.updatedAt || r.createdAt || 0) >= today);
  const count = (d) => todays.filter((r) => r.decision === d).length;
  $('verdicts').textContent = `${count('apply')} / ${count('review')} / ${count('skip')}`;

  const api = state.data.apiConfig;
  $('enableLlm').checked = Boolean(api.enableLlm);
  $('enableSearch').checked = Boolean(api.enableSearch);

  const missing = [];
  if (api.enableLlm && !api.hasLlmKey) missing.push('模型 Key');
  if (api.enableSearch && !api.hasSearchKey) missing.push('检索 Key');
  $('keyState').textContent = missing.length ? `缺 ${missing.join('、')}，当前只跑规则分` : '';
}

for (const id of ['enableLlm', 'enableSearch']) {
  $(id).addEventListener('change', async () => {
    await send('SAVE_API_CONFIG', { apiConfig: { [id]: $(id).checked } });
    load();
  });
}

$('options').addEventListener('click', () => chrome.runtime.openOptionsPage());
$('records').addEventListener('click', () => {
  chrome.tabs.create({ url: chrome.runtime.getURL('src/pages/records.html') });
});

load();
