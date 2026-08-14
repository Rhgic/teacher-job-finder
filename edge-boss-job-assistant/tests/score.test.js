import test from 'node:test';
import assert from 'node:assert/strict';
import { scoreJob, WEIGHTS } from '../src/domain/score.js';
import { normalizeProfile } from '../src/domain/profile.js';
import { GOOD_AI_JOB, makeJob } from './fixtures/jobs.js';

const profile = normalizeProfile({});

test('好岗位规则分应该明显偏高', () => {
  const r = scoreJob(GOOD_AI_JOB, profile);
  assert.ok(r.score >= 80, `实际 ${r.score}：${JSON.stringify(r.breakdown)}`);
});

test('每一项都必须有可读的扣分理由', () => {
  const r = scoreJob(GOOD_AI_JOB, profile);
  assert.equal(r.breakdown.length, Object.keys(WEIGHTS).length);
  for (const b of r.breakdown) {
    assert.ok(b.detail && b.detail.length > 0, `${b.key} 没有 detail`);
    assert.ok(b.points <= b.weight);
  }
});

test('方向词只在 JD 里出现，得分要低于出现在职位名里', () => {
  const inTitle = scoreJob(GOOD_AI_JOB, profile);
  const inJdOnly = scoreJob(
    makeJob({ ...GOOD_AI_JOB, jobTitle: '软件工程师' }),
    profile
  );
  const a = inTitle.breakdown.find((b) => b.key === 'direction').points;
  const b = inJdOnly.breakdown.find((x) => x.key === 'direction').points;
  assert.ok(a > b, `${a} 应该大于 ${b}`);
});

test('HR 发布的岗位在发布者项上要吃亏', () => {
  const boss = scoreJob(GOOD_AI_JOB, profile);
  const hr = scoreJob(makeJob({ ...GOOD_AI_JOB, publisherTitle: '李某·HR' }), profile);
  const a = boss.breakdown.find((b) => b.key === 'publisher').points;
  const b = hr.breakdown.find((x) => x.key === 'publisher').points;
  assert.ok(a > b);
  assert.ok(hr.score < boss.score);
});

test('大厂规模要减分（学历会卡）', () => {
  const big = scoreJob(makeJob({ ...GOOD_AI_JOB, companySizeText: '10000人以上' }), profile);
  const small = scoreJob(GOOD_AI_JOB, profile);
  assert.ok(big.score < small.score);
});

test('警告要转成扣分，最多扣三条', () => {
  const warnings = ['a', 'b', 'c', 'd', 'e'];
  const r = scoreJob(GOOD_AI_JOB, profile, warnings);
  assert.equal(r.penalties.length, 3);
  const base = scoreJob(GOOD_AI_JOB, profile);
  assert.equal(r.score, Math.max(0, base.score - 15));
});

test('完全不相干的岗位分数要低', () => {
  const job = makeJob({
    jobTitle: '前台行政',
    companyName: '某公司',
    jobUrl: 'https://www.zhipin.com/job_detail/z.html',
    salaryText: '4-6K',
    companySizeText: '10000人以上',
    publisherTitle: '张某·人事',
    jobDescription: '负责前台接待、快递收发、会议室预定。'
  });
  const r = scoreJob(job, profile);
  assert.ok(r.score < 30, `实际 ${r.score}`);
});

test('分数永远落在 0-100', () => {
  const r = scoreJob(makeJob({}), profile, ['x', 'y', 'z']);
  assert.ok(r.score >= 0 && r.score <= 100);
});
