import test from 'node:test';
import assert from 'node:assert/strict';
import { decide, DECISION, collectSources } from '../src/domain/decision.js';
import { normalizeProfile } from '../src/domain/profile.js';

const profile = normalizeProfile({});

const PASS = { passed: true, reasons: [], warnings: [] };
const FAIL = { passed: false, reasons: ['职位名含屏蔽词「销售」'], warnings: [] };

function ruleScore(score) {
  return { score, breakdown: [], penalties: [] };
}

function verification({ conflicts = [], withSource = true } = {}) {
  return {
    verdict: 'supported',
    business_match: {
      conclusion: '官网显示主营 AI 客服产品',
      sources: withSource ? [{ url: 'https://example.com/about', quote: 'AI 客服' }] : []
    },
    publisher_check: { conclusion: '', sources: [] },
    going_concern: { conclusion: '', sources: [] },
    consistency_conflicts: conflicts,
    summary: '公开信息支撑 JD'
  };
}

test('硬筛没过 → skip，分数归零', () => {
  const r = decide({ hardFilter: FAIL, ruleScore: ruleScore(90), llmMatch: null, verification: null, profile });
  assert.equal(r.decision, DECISION.SKIP);
  assert.equal(r.finalScore, 0);
  assert.ok(r.headline.includes('销售'));
});

test('高分 + 有来源 + 无矛盾 → apply', () => {
  const r = decide({
    hardFilter: PASS,
    ruleScore: ruleScore(85),
    llmMatch: { match_score: 88, summary: '方向完全对口' },
    verification: verification(),
    profile
  });
  assert.equal(r.decision, DECISION.APPLY);
  assert.equal(r.finalScore, Math.round(0.4 * 85 + 0.6 * 88));
});

test('高风险矛盾一票否决，分数再高也 skip', () => {
  const r = decide({
    hardFilter: PASS,
    ruleScore: ruleScore(95),
    llmMatch: { match_score: 95, summary: '很匹配' },
    verification: verification({
      conflicts: [{ severity: 'high', description: '公开信息显示主业是教育培训招生', sources: [{ url: 'https://x.com', quote: 'y' }] }]
    }),
    profile
  });
  assert.equal(r.decision, DECISION.SKIP);
  assert.ok(r.headline.includes('高风险'));
});

test('中风险矛盾 → 压到 review', () => {
  const r = decide({
    hardFilter: PASS,
    ruleScore: ruleScore(90),
    llmMatch: { match_score: 90, summary: 'ok' },
    verification: verification({ conflicts: [{ severity: 'medium', description: '两处口径不一致', sources: [] }] }),
    profile
  });
  assert.equal(r.decision, DECISION.REVIEW);
});

test('分够但背调没有任何可核验来源 → review，不给绿灯', () => {
  const r = decide({
    hardFilter: PASS,
    ruleScore: ruleScore(90),
    llmMatch: { match_score: 90, summary: 'ok' },
    verification: verification({ withSource: false }),
    profile
  });
  assert.equal(r.decision, DECISION.REVIEW);
  assert.ok(r.headline.includes('来源'));
});

test('模型挂了 → 只用规则分，且封顶到 review', () => {
  const r = decide({
    hardFilter: PASS,
    ruleScore: ruleScore(92),
    llmMatch: null,
    verification: null,
    profile,
    degraded: ['模型匹配失败：超时']
  });
  assert.equal(r.decision, DECISION.REVIEW);
  assert.equal(r.finalScore, 92);
  assert.ok(r.notes.some((n) => n.includes('超时')));
  assert.ok(r.notes.some((n) => n.includes('压到黄灯')));
});

test('分数低于黄灯阈值 → skip', () => {
  const r = decide({
    hardFilter: PASS,
    ruleScore: ruleScore(40),
    llmMatch: { match_score: 40, summary: '不对口' },
    verification: verification(),
    profile
  });
  assert.equal(r.decision, DECISION.SKIP);
});

test('中间分 → review', () => {
  const r = decide({
    hardFilter: PASS,
    ruleScore: ruleScore(70),
    llmMatch: { match_score: 70, summary: '一般' },
    verification: verification(),
    profile
  });
  assert.equal(r.decision, DECISION.REVIEW);
});

test('阈值可配：调低绿灯线后同一岗位能变绿', () => {
  const loose = normalizeProfile({ applyThreshold: 65, reviewThreshold: 50 });
  const args = {
    hardFilter: PASS,
    ruleScore: ruleScore(70),
    llmMatch: { match_score: 70, summary: '一般' },
    verification: verification()
  };
  assert.equal(decide({ ...args, profile }).decision, DECISION.REVIEW);
  assert.equal(decide({ ...args, profile: loose }).decision, DECISION.APPLY);
});

test('collectSources 跨桶去重', () => {
  const v = {
    business_match: { sources: [{ url: 'https://a.com/x', quote: '1' }] },
    publisher_check: { sources: [{ url: 'https://a.com/x', quote: '1' }] },
    going_concern: { sources: [{ url: 'https://b.com/y', quote: '2' }] },
    consistency_conflicts: [{ sources: [{ url: 'https://c.com/z', quote: '3' }] }]
  };
  assert.equal(collectSources(v).length, 3);
  assert.equal(collectSources(null).length, 0);
});
