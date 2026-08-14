/**
 * chrome.storage.local 封装（设计文档 §8）。
 * 所有数据只落在本机，提供一键导出和一键清除。
 */

export const KEYS = {
  PROFILE: 'profile',
  API: 'apiConfig',
  CACHE: 'evalCache',
  RECORDS: 'records',
  USAGE: 'usage',
  SEND: 'sendConfig',
  SENT: 'sentLog',
  SCHEMA_VERSION: 'schemaVersion'
};

export const CURRENT_SCHEMA_VERSION = 1;

/** 评估结果缓存上限。同一岗位翻回去看不该重新烧钱。 */
const MAX_CACHE_ENTRIES = 400;
const MAX_RECORDS = 1000;
const CACHE_TTL_MS = 7 * 24 * 60 * 60 * 1000;

export const DEFAULT_API_CONFIG = {
  llmBaseUrl: 'https://api.deepseek.com',
  llmModel: 'deepseek-chat',
  llmApiKey: '',
  searchProvider: 'tavily', // tavily | serper | none
  searchApiKey: '',
  /** 每天最多几次模型调用，防止翻页翻出一笔账单。 */
  dailyLlmLimit: 60,
  /** 关掉就只跑规则分，完全不联网。 */
  enableLlm: true,
  enableSearch: true
};

/**
 * 发送相关配置。autoSend 默认关 —— 打开它等于把封号风险揽到自己身上，
 * 必须是用户在配置页主动拧的，不能是装上就生效。
 */
export const DEFAULT_SEND_CONFIG = {
  autoSend: false,
  /** 黄灯岗位是否也允许自动发。默认否，黄灯只能人工点。 */
  allowReviewSend: false,
  dailySendLimit: 30,
  /** 只在这个时段发。半夜发招呼语除了显得不正常没有任何好处。 */
  workingHours: [9, 22],
  /** 生成招呼语但不发，只填进输入框。介于纯只读和全自动之间。 */
  fillOnly: true
};

export async function getSendConfig() {
  const saved = await get(KEYS.SEND, {});
  return { ...DEFAULT_SEND_CONFIG, ...saved };
}

/* ---------------- 已发送台账 ---------------- */

/**
 * 记录已经打过招呼的岗位。这是防重复的唯一依据，
 * 所以写在点击之前，宁可多记一条也不能漏记。
 */
export async function markSent(jobKey, payload) {
  const log = await get(KEYS.SENT, {});
  log[jobKey] = { ...payload, at: Date.now() };
  await set(KEYS.SENT, log);
}

export async function wasSent(jobKey) {
  const log = await get(KEYS.SENT, {});
  return Boolean(log[jobKey]);
}

export async function getSentLog() {
  return get(KEYS.SENT, {});
}

export async function sentToday() {
  const log = await get(KEYS.SENT, {});
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  return Object.values(log).filter((e) => (e.at || 0) >= start.getTime()).length;
}

export async function get(key, fallback) {
  const res = await chrome.storage.local.get(key);
  return res[key] === undefined ? fallback : res[key];
}

export async function set(key, value) {
  await chrome.storage.local.set({ [key]: value });
}

export async function getApiConfig() {
  const saved = await get(KEYS.API, {});
  return { ...DEFAULT_API_CONFIG, ...saved };
}

/* ---------------- 评估缓存 ---------------- */

export async function getCached(jobKey) {
  const cache = await get(KEYS.CACHE, {});
  const entry = cache[jobKey];
  if (!entry) return null;
  if (Date.now() - entry.savedAt > CACHE_TTL_MS) return null;
  return entry;
}

export async function putCached(jobKey, result) {
  const cache = await get(KEYS.CACHE, {});
  cache[jobKey] = { ...result, savedAt: Date.now() };
  const keys = Object.keys(cache);
  if (keys.length > MAX_CACHE_ENTRIES) {
    keys
      .sort((a, b) => (cache[a].savedAt || 0) - (cache[b].savedAt || 0))
      .slice(0, keys.length - MAX_CACHE_ENTRIES)
      .forEach((k) => delete cache[k]);
  }
  await set(KEYS.CACHE, cache);
}

/* ---------------- 决策流水 ---------------- */

/**
 * 记录一次评估。只记结论和证据，不记任何「已发送」状态 —— 这个版本不发东西。
 */
export async function appendRecord(record) {
  const records = await get(KEYS.RECORDS, []);
  const idx = records.findIndex((r) => r.jobKey === record.jobKey);
  if (idx >= 0) records[idx] = { ...records[idx], ...record, updatedAt: Date.now() };
  else records.unshift({ ...record, createdAt: Date.now(), updatedAt: Date.now() });
  await set(KEYS.RECORDS, records.slice(0, MAX_RECORDS));
}

export async function getRecords() {
  return get(KEYS.RECORDS, []);
}

/* ---------------- 用量 ---------------- */

function today() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

export async function getUsage() {
  const usage = await get(KEYS.USAGE, {});
  const day = today();
  if (usage.day !== day) return { day, llmCalls: 0, searchCalls: 0, evaluated: 0 };
  return usage;
}

export async function bumpUsage(field, delta = 1) {
  const usage = await getUsage();
  usage[field] = (usage[field] || 0) + delta;
  await set(KEYS.USAGE, usage);
  return usage;
}

/** 返回 true 表示还能调模型。 */
export async function canCallLlm(apiConfig) {
  const usage = await getUsage();
  return (usage.llmCalls || 0) < (apiConfig.dailyLlmLimit || 0);
}

/* ---------------- 导出 / 清除 ---------------- */

export async function exportAll() {
  const all = await chrome.storage.local.get(null);
  // 导出不带 Key，免得随手发给别人
  const api = { ...(all[KEYS.API] || {}) };
  delete api.llmApiKey;
  delete api.searchApiKey;
  return { ...all, [KEYS.API]: api, exportedAt: new Date().toISOString() };
}

export async function clearAll() {
  await chrome.storage.local.clear();
}

export async function migrate() {
  const version = await get(KEYS.SCHEMA_VERSION, 0);
  if (version === CURRENT_SCHEMA_VERSION) return;
  await set(KEYS.SCHEMA_VERSION, CURRENT_SCHEMA_VERSION);
}
