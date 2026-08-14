/**
 * 发送前的最后一道闸（设计文档 §5.1）。
 *
 * 纯函数，没有副作用，好测。真正点页面的代码必须先过这里，
 * 任何一条不过就不发，而且不重试 —— 重试是重复打招呼的头号来源。
 */

import { validateGreeting } from './greeting.js';

export const BLOCK = {
  DISABLED: 'disabled',
  NOT_APPLY: 'not_apply',
  ALREADY_SENT: 'already_sent',
  DAILY_LIMIT: 'daily_limit',
  PAGE_MISMATCH: 'page_mismatch',
  BAD_GREETING: 'bad_greeting',
  OUTSIDE_HOURS: 'outside_hours'
};

function normalize(s) {
  return String(s || '').replace(/\s+/g, '').toLowerCase();
}

/**
 * @param {object} input
 * @param {object} input.snapshot        队列里的岗位快照
 * @param {object} input.pageSnapshot    发送这一刻页面上重新抓的快照
 * @param {string} input.greeting        要发的正文
 * @param {string} input.decision        评估结论
 * @param {boolean} input.alreadySent    这个岗位是否已经打过招呼
 * @param {number} input.sentToday
 * @param {object} input.config          { autoSend, dailySendLimit, workingHours:[start,end], allowReviewSend }
 * @param {object} input.profile
 * @param {Date}   [input.now]
 * @returns {{allowed:boolean, blockedBy:string|null, reasons:string[]}}
 */
export function canSend({
  snapshot,
  pageSnapshot,
  greeting,
  decision,
  alreadySent,
  sentToday,
  config,
  profile,
  now = new Date()
}) {
  const reasons = [];
  const block = (code, why) => {
    reasons.push(why);
    return { allowed: false, blockedBy: code, reasons };
  };

  if (!config.autoSend) return block(BLOCK.DISABLED, '自动发送开关没打开');

  // 只有绿灯能自动发。黄灯要发必须人工点，且走 allowReviewSend
  if (decision === 'skip') return block(BLOCK.NOT_APPLY, '这个岗位判的是「别投」');
  if (decision !== 'apply' && !config.allowReviewSend) {
    return block(BLOCK.NOT_APPLY, '黄灯岗位默认不自动发，要发请人工确认');
  }

  if (alreadySent) return block(BLOCK.ALREADY_SENT, '这个岗位已经打过招呼了');

  if (sentToday >= config.dailySendLimit) {
    return block(BLOCK.DAILY_LIMIT, `今天已发 ${sentToday} 条，达到上限 ${config.dailySendLimit}`);
  }

  // 页面有没有在你决策之后跳走 —— 发错公司比不发严重得多
  if (!pageSnapshot) return block(BLOCK.PAGE_MISMATCH, '发送前没能重新读取页面');
  if (normalize(pageSnapshot.companyName) !== normalize(snapshot.companyName)) {
    return block(
      BLOCK.PAGE_MISMATCH,
      `页面公司「${pageSnapshot.companyName}」和快照「${snapshot.companyName}」对不上`
    );
  }
  if (normalize(pageSnapshot.jobTitle) !== normalize(snapshot.jobTitle)) {
    return block(BLOCK.PAGE_MISMATCH, `页面职位「${pageSnapshot.jobTitle}」和快照「${snapshot.jobTitle}」对不上`);
  }

  const check = validateGreeting(greeting, profile);
  if (!check.ok) return block(BLOCK.BAD_GREETING, `招呼语没过校验：${check.errors.join('；')}`);

  const [start, end] = config.workingHours || [9, 22];
  const hour = now.getHours();
  if (hour < start || hour >= end) {
    return block(BLOCK.OUTSIDE_HOURS, `现在 ${hour} 点，不在设定的 ${start}–${end} 点发送时段内`);
  }

  return { allowed: true, blockedBy: null, reasons: [] };
}
