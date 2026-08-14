import test from 'node:test';
import assert from 'node:assert/strict';
import { canSend, BLOCK } from '../src/domain/send-guard.js';
import { normalizeProfile } from '../src/domain/profile.js';
import { GOOD_AI_JOB } from './fixtures/jobs.js';

const profile = normalizeProfile({});

const GREETING =
  '您好，看到岗位要求做 Agent 工具编排和 RAG 检索优化。我做过一个智能出行 Agent，用原生 Function Calling 编排多轮规划，' +
  '没套框架；另一个教师招聘项目用 RAG 做公告问答，回答带可点击出处。两个都在 GitHub 上，带 Docker 和测试，方便的话我发您链接。';

const CONFIG = {
  autoSend: true,
  allowReviewSend: false,
  dailySendLimit: 30,
  workingHours: [9, 22],
  fillOnly: false
};

/** 工作时间内的一个时刻，避免测试在半夜跑就红。 */
const NOON = new Date('2026-08-14T12:00:00');

function base(overrides = {}) {
  return {
    snapshot: GOOD_AI_JOB,
    pageSnapshot: GOOD_AI_JOB,
    greeting: GREETING,
    decision: 'apply',
    alreadySent: false,
    sentToday: 0,
    config: CONFIG,
    profile,
    now: NOON,
    ...overrides
  };
}

test('全部条件正常 → 放行', () => {
  const r = canSend(base());
  assert.equal(r.allowed, true, r.reasons.join('；'));
});

test('开关没开 → 拦', () => {
  const r = canSend(base({ config: { ...CONFIG, autoSend: false } }));
  assert.equal(r.allowed, false);
  assert.equal(r.blockedBy, BLOCK.DISABLED);
});

test('红灯岗位 → 拦，且理由说清楚', () => {
  const r = canSend(base({ decision: 'skip' }));
  assert.equal(r.allowed, false);
  assert.equal(r.blockedBy, BLOCK.NOT_APPLY);
});

test('黄灯岗位默认拦，开了 allowReviewSend 才放', () => {
  assert.equal(canSend(base({ decision: 'review' })).blockedBy, BLOCK.NOT_APPLY);
  const loose = canSend(base({ decision: 'review', config: { ...CONFIG, allowReviewSend: true } }));
  assert.equal(loose.allowed, true, loose.reasons.join('；'));
});

test('已经打过招呼 → 拦。这是防重复的关键路径', () => {
  const r = canSend(base({ alreadySent: true }));
  assert.equal(r.allowed, false);
  assert.equal(r.blockedBy, BLOCK.ALREADY_SENT);
});

test('到了日上限 → 拦', () => {
  const r = canSend(base({ sentToday: 30 }));
  assert.equal(r.allowed, false);
  assert.equal(r.blockedBy, BLOCK.DAILY_LIMIT);
  assert.ok(r.reasons[0].includes('30'));
});

test('页面已经翻到别的公司了 → 拦。发错公司比不发严重得多', () => {
  const r = canSend(base({ pageSnapshot: { ...GOOD_AI_JOB, companyName: '另一家完全不同的公司' } }));
  assert.equal(r.allowed, false);
  assert.equal(r.blockedBy, BLOCK.PAGE_MISMATCH);
  assert.ok(r.reasons[0].includes('另一家完全不同的公司'));
});

test('页面职位对不上 → 拦', () => {
  const r = canSend(base({ pageSnapshot: { ...GOOD_AI_JOB, jobTitle: 'Java 开发工程师' } }));
  assert.equal(r.blockedBy, BLOCK.PAGE_MISMATCH);
});

test('公司名只差空格大小写不算对不上', () => {
  const r = canSend(base({ pageSnapshot: { ...GOOD_AI_JOB, companyName: ' 深圳某某智能科技有限公司 ' } }));
  assert.equal(r.allowed, true, r.reasons.join('；'));
});

test('没能重新读到页面 → 拦，不赌', () => {
  const r = canSend(base({ pageSnapshot: null }));
  assert.equal(r.blockedBy, BLOCK.PAGE_MISMATCH);
});

test('招呼语没过校验 → 拦', () => {
  const r = canSend(base({ greeting: '贵司前景广阔，恳请给个机会，我准确率做到过 95%。' }));
  assert.equal(r.allowed, false);
  assert.equal(r.blockedBy, BLOCK.BAD_GREETING);
});

test('空招呼语 → 拦', () => {
  assert.equal(canSend(base({ greeting: '' })).blockedBy, BLOCK.BAD_GREETING);
});

test('非工作时间 → 拦。半夜发招呼语没有任何好处', () => {
  const r = canSend(base({ now: new Date('2026-08-14T03:00:00') }));
  assert.equal(r.allowed, false);
  assert.equal(r.blockedBy, BLOCK.OUTSIDE_HOURS);
});

test('时段边界：9 点放行，22 点拦', () => {
  assert.equal(canSend(base({ now: new Date('2026-08-14T09:00:00') })).allowed, true);
  assert.equal(canSend(base({ now: new Date('2026-08-14T22:00:00') })).blockedBy, BLOCK.OUTSIDE_HOURS);
});

test('多条不满足时，先报最该先看的那条', () => {
  const r = canSend(base({ alreadySent: true, sentToday: 99, greeting: '' }));
  assert.equal(r.blockedBy, BLOCK.ALREADY_SENT);
  assert.equal(r.reasons.length, 1);
});
