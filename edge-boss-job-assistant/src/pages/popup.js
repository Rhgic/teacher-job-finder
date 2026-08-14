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
  const sendConfig = state.data.sendConfig || {};
  $('evaluated').textContent = usage.evaluated || 0;
  $('sent').textContent = `${state.data.sentToday ?? 0} / ${sendConfig.dailySendLimit ?? '-'}`;
  $('llmCalls').textContent = `${usage.llmCalls || 0} / ${state.data.apiConfig.dailyLlmLimit ?? '-'}`;
  $('searchCalls').textContent = usage.searchCalls || 0;

  const today = todayStart();
  const todays = (records?.data?.records || []).filter((r) => (r.updatedAt || r.createdAt || 0) >= today);
  const count = (d) => todays.filter((r) => r.decision === d).length;
  $('verdicts').textContent = `${count('apply')} / ${count('review')} / ${count('skip')}`;

  // 结果不明的发送必须显眼，这是唯一需要人去 BOSS 上确认的东西
  const attention = todays.filter((r) => r.needsAttention).length;
  $('attentionRow').style.display = attention > 0 ? 'flex' : 'none';
  $('attention').textContent = attention;

  const api = state.data.apiConfig;
  $('enableLlm').checked = Boolean(api.enableLlm);
  $('enableSearch').checked = Boolean(api.enableSearch);

  const armed = sendConfig.autoSend && !sendConfig.fillOnly;
  $('autoSend').checked = Boolean(armed);
  $('sendState').textContent = armed
    ? '自动发送开着，绿灯岗位不用你点'
    : '只填不发，发送键你自己按';
  $('sendState').style.color = armed ? 'var(--red)' : 'var(--muted)';

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

$('autoSend').addEventListener('change', async () => {
  const on = $('autoSend').checked;
  if (on && !confirm('打开后它会自己点发送键。平台对自动化投递是限制账号处理的，确定？')) {
    $('autoSend').checked = false;
    return;
  }
  // 两个开关是一体的：要自动发就得同时关掉「只填不发」
  await send('SAVE_SEND_CONFIG', { sendConfig: { autoSend: on, fillOnly: !on } });
  load();
});

$('options').addEventListener('click', () => chrome.runtime.openOptionsPage());
$('records').addEventListener('click', () => {
  chrome.tabs.create({ url: chrome.runtime.getURL('src/pages/records.html') });
});

load();
