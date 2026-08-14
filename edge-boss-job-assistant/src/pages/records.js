/** 记录页。全部用 DOM 构造，不拼 innerHTML —— 表里存着模型和检索来的文本。 */

const $ = (id) => document.getElementById(id);
const LABEL = { apply: '建议投', review: '待定', skip: '别投' };

let all = [];

function send(type, payload) {
  return new Promise((resolve) => chrome.runtime.sendMessage({ type, payload }, resolve));
}

function h(tag, attrs = {}, children = []) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') el.className = v;
    else if (v !== undefined && v !== null) el.setAttribute(k, v);
  }
  for (const c of [].concat(children)) {
    if (c === null || c === undefined || c === false) continue;
    el.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
  }
  return el;
}

function safeLink(url, text) {
  if (!/^https?:\/\//i.test(String(url || ''))) return h('span', {}, String(text ?? ''));
  return h('a', { href: url, target: '_blank', rel: 'noopener noreferrer' }, String(text ?? url));
}

function fmtTime(ts) {
  if (!ts) return '';
  const d = new Date(ts);
  return `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

function filtered() {
  const decision = $('filterDecision').value;
  const action = $('filterAction').value;
  const q = $('search').value.trim().toLowerCase();
  return all.filter((r) => {
    if (decision && r.decision !== decision) return false;
    if (action === 'none' && r.userAction) return false;
    if (action && action !== 'none' && r.userAction !== action) return false;
    if (q) {
      const hay = `${r.companyName || ''} ${r.jobTitle || ''}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

function render() {
  const rows = filtered();
  const tbody = $('rows');
  while (tbody.firstChild) tbody.removeChild(tbody.firstChild);

  for (const r of rows) {
    const sources = (r.sources || []).slice(0, 3).map((s) => safeLink(s.url, hostOf(s.url)));
    tbody.appendChild(
      h('tr', {}, [
        h('td', { class: 'muted' }, fmtTime(r.updatedAt || r.createdAt)),
        h('td', {}, h('span', { class: `tag ${r.decision}` }, LABEL[r.decision] || r.decision || '')),
        h('td', {}, String(r.finalScore ?? '')),
        h('td', {}, safeLink(r.jobUrl, r.jobTitle || '')),
        h('td', {}, r.companyName || ''),
        h('td', {}, r.salaryText || ''),
        h('td', { class: 'muted' }, r.headline || ''),
        h('td', { class: 'src' }, sources.length ? sources : h('span', { class: 'muted' }, '无')),
        h('td', {}, r.userAction === 'applied' ? '我投了' : r.userAction === 'skipped' ? '我跳过' : '')
      ])
    );
  }
  $('count').textContent = `${rows.length} / ${all.length} 条`;
}

function hostOf(url) {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

function download(content, filename, type) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function csvCell(v) {
  const s = String(v ?? '').replace(/"/g, '""');
  return `"${s}"`;
}

$('exportCsv').addEventListener('click', () => {
  const rows = filtered();
  const header = ['时间', '决策', '分数', '职位', '公司', '薪资', '发布者', '结论', '证据URL', '我的标记'];
  const lines = [header.map(csvCell).join(',')];
  for (const r of rows) {
    lines.push(
      [
        fmtTime(r.updatedAt || r.createdAt),
        LABEL[r.decision] || r.decision,
        r.finalScore,
        r.jobTitle,
        r.companyName,
        r.salaryText,
        r.publisherTitle,
        r.headline,
        (r.sources || []).map((s) => s.url).join(' | '),
        r.userAction || ''
      ]
        .map(csvCell)
        .join(',')
    );
  }
  // ﻿ 让 Excel 认出 UTF-8，不然中文全是乱码
  download('﻿' + lines.join('\n'), `boss-records-${new Date().toISOString().slice(0, 10)}.csv`, 'text/csv');
});

$('exportJson').addEventListener('click', () => {
  download(
    JSON.stringify(filtered(), null, 2),
    `boss-records-${new Date().toISOString().slice(0, 10)}.json`,
    'application/json'
  );
});

for (const id of ['filterDecision', 'filterAction']) $(id).addEventListener('change', render);
$('search').addEventListener('input', render);

(async () => {
  const res = await send('GET_RECORDS');
  all = res?.data?.records || [];
  render();
})();
