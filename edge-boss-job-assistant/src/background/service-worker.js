/**
 * Service Worker：消息路由 + 评估调度。
 *
 * 这个扩展没有 alarms、没有队列、没有定时任务，也没有任何向页面注入点击的能力。
 * 它只在你打开一个岗位页时算一次分，然后把结论和证据交给你。
 */

import { evaluate } from './pipeline.js';
import { normalizeProfile } from '../domain/profile.js';
import { jobKey } from '../domain/job.js';
import * as store from '../storage/store.js';

chrome.runtime.onInstalled.addListener(() => {
  store.migrate().catch(() => {});
});

/** 同一岗位并发请求只跑一次，避免侧边栏重复渲染时重复计费。 */
const inflight = new Map();

const handlers = {
  async EVALUATE_JOB({ snapshot, force }) {
    const key = jobKey(snapshot);

    if (!force) {
      const cached = await store.getCached(key);
      if (cached) return { ...cached.result, fromCache: true };
    }

    if (inflight.has(key)) return inflight.get(key);

    const task = (async () => {
      const profile = normalizeProfile(await store.get(store.KEYS.PROFILE, null));
      const apiConfig = await store.getApiConfig();
      const result = await evaluate(snapshot, profile, apiConfig);

      if (result.ok) {
        await store.putCached(key, { result });
        await store.bumpUsage('evaluated');
        await store.appendRecord({
          jobKey: key,
          jobTitle: snapshot.jobTitle,
          companyName: snapshot.companyName,
          jobUrl: snapshot.jobUrl,
          salaryText: snapshot.salaryText,
          publisherTitle: snapshot.publisherTitle,
          decision: result.decision,
          finalScore: result.finalScore,
          headline: result.headline,
          sources: result.sources,
          conflicts: result.conflicts,
          notes: result.notes
        });
      }
      return result;
    })().finally(() => inflight.delete(key));

    inflight.set(key, task);
    return task;
  },

  async GET_STATE() {
    const [profile, apiConfig, usage] = await Promise.all([
      store.get(store.KEYS.PROFILE, null),
      store.getApiConfig(),
      store.getUsage()
    ]);
    const safeApi = { ...apiConfig };
    // 不把 Key 回传给页面，只回传「配没配」
    safeApi.hasLlmKey = Boolean(safeApi.llmApiKey);
    safeApi.hasSearchKey = Boolean(safeApi.searchApiKey);
    delete safeApi.llmApiKey;
    delete safeApi.searchApiKey;
    return { profile: normalizeProfile(profile), apiConfig: safeApi, usage };
  },

  async GET_API_CONFIG_FULL() {
    // 只有 options 页会用；popup 和 content script 不调这个
    return store.getApiConfig();
  },

  async SAVE_PROFILE({ profile }) {
    await store.set(store.KEYS.PROFILE, normalizeProfile(profile));
    await store.set(store.KEYS.CACHE, {}); // 画像变了，旧结论作废
    return { saved: true };
  },

  async SAVE_API_CONFIG({ apiConfig }) {
    const current = await store.getApiConfig();
    await store.set(store.KEYS.API, { ...current, ...apiConfig });
    return { saved: true };
  },

  async GET_RECORDS() {
    return { records: await store.getRecords() };
  },

  async MARK_RECORD({ jobKey: key, userAction, userNote }) {
    await store.appendRecord({ jobKey: key, userAction, userNote });
    return { saved: true };
  },

  async EXPORT_ALL() {
    return { data: await store.exportAll() };
  },

  async CLEAR_ALL() {
    await store.clearAll();
    return { cleared: true };
  }
};

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  const handler = handlers[msg?.type];
  if (!handler) {
    sendResponse({ ok: false, error: `未知消息类型 ${msg?.type}` });
    return false;
  }
  Promise.resolve(handler(msg.payload || {}))
    .then((data) => sendResponse({ ok: true, data }))
    .catch((e) => sendResponse({ ok: false, error: e?.message || String(e) }));
  return true; // 异步响应
});
