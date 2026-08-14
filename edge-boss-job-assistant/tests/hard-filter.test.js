import test from 'node:test';
import assert from 'node:assert/strict';
import { runHardFilter } from '../src/domain/hard-filter.js';
import { normalizeProfile } from '../src/domain/profile.js';
import {
  GOOD_AI_JOB,
  FAKE_AI_SALES_JOB,
  OUTSOURCE_JOB,
  OVER_QUALIFIED_JOB,
  WRONG_CITY_JOB,
  makeJob
} from './fixtures/jobs.js';

const profile = normalizeProfile({});

test('好岗位能通过硬筛', () => {
  const r = runHardFilter(GOOD_AI_JOB, profile);
  assert.equal(r.passed, true, r.reasons.join('；'));
});

test('职位名带销售 → 直接否', () => {
  const r = runHardFilter(FAKE_AI_SALES_JOB, profile);
  assert.equal(r.passed, false);
  assert.ok(r.reasons.some((x) => x.includes('销售')));
});

test('JD 里的外包驻场特征 → 直接否', () => {
  const r = runHardFilter(OUTSOURCE_JOB, profile);
  assert.equal(r.passed, false);
  assert.ok(r.reasons.some((x) => x.includes('外包') || x.includes('驻场')));
});

test('学历和经验超标 → 直接否，两条理由都要给出来', () => {
  const r = runHardFilter(OVER_QUALIFIED_JOB, profile);
  assert.equal(r.passed, false);
  assert.ok(r.reasons.some((x) => x.includes('学历')));
  assert.ok(r.reasons.some((x) => x.includes('经验')));
});

test('城市不对 → 直接否', () => {
  const r = runHardFilter(WRONG_CITY_JOB, profile);
  assert.equal(r.passed, false);
  assert.ok(r.reasons.some((x) => x.includes('杭州')));
});

test('薪资上限低于底线 → 直接否', () => {
  const job = makeJob({ ...GOOD_AI_JOB, salaryText: '4-6K' });
  const r = runHardFilter(job, profile);
  assert.equal(r.passed, false);
  assert.ok(r.reasons.some((x) => x.includes('6K')));
});

test('日结 → 直接否', () => {
  const job = makeJob({ ...GOOD_AI_JOB, salaryText: '300-500元/天' });
  const r = runHardFilter(job, profile);
  assert.equal(r.passed, false);
});

test('给销售团队做系统的技术岗不该被误杀，只警告', () => {
  const job = makeJob({
    ...GOOD_AI_JOB,
    jobTitle: 'Python后端开发工程师',
    jobDescription: '负责为销售团队开发 CRM 后台，使用 Python 和 FastAPI，配合 Docker 部署。'
  });
  const r = runHardFilter(job, profile);
  assert.equal(r.passed, true, r.reasons.join('；'));
  assert.ok(r.warnings.some((w) => w.includes('销售')));
});

test('面议只警告不否决', () => {
  const job = makeJob({ ...GOOD_AI_JOB, salaryText: '面议' });
  const r = runHardFilter(job, profile);
  assert.equal(r.passed, true);
  assert.ok(r.warnings.some((w) => w.includes('面议')));
});

test('缺字段时不该瞎否决', () => {
  const job = makeJob({
    jobTitle: 'AI应用开发',
    companyName: '某公司',
    jobUrl: 'https://www.zhipin.com/job_detail/x.html'
  });
  const r = runHardFilter(job, profile);
  assert.equal(r.passed, true, r.reasons.join('；'));
});
