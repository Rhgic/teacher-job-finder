import test from 'node:test';
import assert from 'node:assert/strict';
import {
  parseSalary,
  parseExperience,
  parseEducationRank,
  parseCompanySize,
  jobKey,
  isUsableSnapshot,
  emptySnapshot
} from '../src/domain/job.js';

test('薪资：常见 K 区间', () => {
  assert.deepEqual(pick(parseSalary('8-13K')), { min: 8, max: 13, unit: 'month' });
  assert.deepEqual(pick(parseSalary('10-15K·13薪')), { min: 10, max: 15, unit: 'month' });
  assert.equal(parseSalary('10-15K·13薪').months, 13);
  assert.deepEqual(pick(parseSalary('8k-12k')), { min: 8, max: 12, unit: 'month' });
});

test('薪资：万为单位换算成 K', () => {
  assert.deepEqual(pick(parseSalary('1.5-2万')), { min: 15, max: 20, unit: 'month' });
});

test('薪资：智联/51job 的「两头都带单位」写法', () => {
  assert.deepEqual(pick(parseSalary('1.2万-1.8万')), { min: 12, max: 18, unit: 'month' });
  assert.deepEqual(pick(parseSalary('8千-1.2万')), { min: 8, max: 12, unit: 'month' });
  assert.deepEqual(pick(parseSalary('6千-9千')), { min: 6, max: 9, unit: 'month' });
});

test('薪资：千为单位不能被当成万', () => {
  const s = parseSalary('6-9千');
  assert.equal(s.min, 6);
  assert.equal(s.max, 9);
});

test('薪资：日结/时结单独标记，不折算月薪', () => {
  const day = parseSalary('300-500元/天');
  assert.equal(day.unit, 'day');
  assert.equal(day.min, 300);
  const hour = parseSalary('30-50元/小时');
  assert.equal(hour.unit, 'hour');
});

test('薪资：面议', () => {
  const s = parseSalary('面议');
  assert.equal(s.negotiable, true);
  assert.equal(s.max, null);
});

test('薪资：空值不炸', () => {
  assert.equal(parseSalary('').max, null);
  assert.equal(parseSalary(undefined).max, null);
});

test('经验：应届和不限都算 0 年', () => {
  assert.equal(parseExperience('经验不限').minYears, 0);
  assert.equal(parseExperience('在校/应届').minYears, 0);
  assert.equal(parseExperience('1年以内').minYears, 0);
});

test('经验：区间取下限，以上取本身', () => {
  assert.equal(parseExperience('1-3年').minYears, 1);
  assert.equal(parseExperience('3-5年').minYears, 3);
  assert.equal(parseExperience('5年以上').minYears, 5);
});

test('学历：等级比较', () => {
  assert.equal(parseEducationRank('学历不限'), 0);
  assert.equal(parseEducationRank('大专'), 3);
  assert.equal(parseEducationRank('本科'), 4);
  assert.ok(parseEducationRank('硕士') > parseEducationRank('本科'));
  assert.equal(parseEducationRank(''), null);
});

test('公司规模解析', () => {
  assert.deepEqual(parseCompanySize('20-99人').min, 20);
  assert.equal(parseCompanySize('10000人以上').max, Infinity);
  assert.equal(parseCompanySize('未知'), null);
});

test('jobKey：优先用 URL 里的岗位 id', () => {
  const a = { jobUrl: 'https://www.zhipin.com/job_detail/abc123~.html', companyName: 'X', jobTitle: 'Y' };
  assert.equal(jobKey(a), 'job:abc123~');
});

test('jobKey：拿不到 id 时退回公司+职位，且忽略空格大小写', () => {
  const a = { jobUrl: 'https://www.zhipin.com/x', companyName: '深圳 某某 科技', jobTitle: 'AI 应用开发' };
  const b = { jobUrl: 'https://www.zhipin.com/y', companyName: '深圳某某科技', jobTitle: 'AI应用开发' };
  assert.equal(jobKey(a), jobKey(b));
});

test('快照可用性：缺公司名就不可用', () => {
  const s = { ...emptySnapshot(), jobTitle: 'AI 工程师', jobUrl: 'https://x' };
  assert.equal(isUsableSnapshot(s), false);
  s.companyName = '某公司';
  assert.equal(isUsableSnapshot(s), true);
});

function pick(s) {
  return { min: s.min, max: s.max, unit: s.unit };
}
