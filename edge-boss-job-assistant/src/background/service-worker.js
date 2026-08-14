/**
 * Service Worker：消息路由 + 评估调度。
 *
 * 这个扩展没有 alarms、没有队列、没有定时任务，也没有任何向页面注入点击的能力。
 * 它只在你打开一个岗位页时算一次分，然后把结论和证据交给你。
 */

import { evaluate } from './pipeline.js';
import { normalizeProfile } from '../domain/profile.js';
import { jobKey } from '../domain/job.js';
import { canSend } from '../domain/send-guard.js';
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
    const [profile, apiConfig, usage, sendConfig, sentToday] = await Promise.all([
      store.get(store.KEYS.PROFILE, null),
      store.getApiConfig(),
      store.getUsage(),
      store.getSendConfig(),
      store.sentToday()
    ]);
    const safeApi = { ...apiConfig };
    // 不把 Key 回传给页面，只回传「配没配」
    safeApi.hasLlmKey = Boolean(safeApi.llmApiKey);
    safeApi.hasSearchKey = Boolean(safeApi.searchApiKey);
    delete safeApi.llmApiKey;
    delete safeApi.searchApiKey;
    return { profile: normalizeProfile(profile), apiConfig: safeApi, usage, sendConfig, sentToday };
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

  async GET_SEND_CONFIG() {
    return store.getSendConfig();
  },

  async SAVE_SEND_CONFIG({ sendConfig }) {
    const current = await store.getSendConfig();
    await store.set(store.KEYS.SEND, { ...current, ...sendConfig });
    return { saved: true };
  },

  /**
   * 发送闸门。判断全在这里做，content script 只能问、不能自己决定。
   * 放行的同时就把账记上 —— content script 拿到 allowed 之后才碰页面。
   */
  async CHECK_SEND({ jobKey: key, snapshot, pageSnapshot, greeting, decision, auto }) {
    const [profile, sendConfig, alreadySent, sentToday] = await Promise.all([
      store.get(store.KEYS.PROFILE, null).then(normalizeProfile),
      store.getSendConfig(),
      store.wasSent(key),
      store.sentToday()
    ]);

    // 人工点「填入并发送」时，autoSend 开关不该拦着 —— 那个开关管的是「不用你点」
    const effective = auto ? sendConfig : { ...sendConfig, autoSend: true, allowReviewSend: true };

    const verdict = canSend({
      snapshot,
      pageSnapshot,
      greeting,
      decision,
      alreadySent,
      sentToday,
      config: effective,
      profile
    });

    if (verdict.allowed) {
      await store.markSent(key, {
        jobTitle: snapshot.jobTitle,
        companyName: snapshot.companyName,
        jobUrl: snapshot.jobUrl,
        greeting,
        auto,
        status: 'pending'
      });
    }

    return { ...verdict, fillOnly: sendConfig.fillOnly };
  },

  /** content script 汇报执行结果。这里只如实记录，不做补救、不重试。 */
  async CONFIRM_SENT({ jobKey: key, status, reason }) {
    const log = await store.getSentLog();
    const entry = log[key];

    // 这几种状态说明压根没点下去，把账撤了，免得这个岗位被永久锁死
    const neverClicked = ['fill_failed', 'no_button', 'disabled', 'captcha'];
    if (entry && neverClicked.includes(status)) {
      delete log[key];
      await store.set(store.KEYS.SENT, log);
    } else if (entry) {
      log[key] = { ...entry, status, reason: reason || '' };
      await store.set(store.KEYS.SENT, log);
    }

    await store.appendRecord({
      jobKey: key,
      sendStatus: status,
      sendReason: reason || '',
      sentAt: Date.now(),
      needsAttention: status === 'unknown' || status === 'captcha'
    });
    return { recorded: true };
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
