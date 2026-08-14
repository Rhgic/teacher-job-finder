/**
 * content script 是 classic script，不能 import，所以在 vm 里跑一遍拿到命名空间。
 *
 * 注意这里测的是「文本兜底」那一层。CSS 选择器只能对着真站点验，
 * 扩展里的「选择器自检」按钮就是干这个的。
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { PAGE_TEXT_SAMPLE } from './fixtures/jobs.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const source = fs.readFileSync(path.join(here, '../src/content/boss-adapter.js'), 'utf8');

const context = vm.createContext({});
vm.runInContext(source, context);
const NS = context.EBJA;

test('适配器在没有 DOM 的环境里也能加载', () => {
  assert.ok(NS);
  assert.equal(typeof NS.extractSnapshot, 'function');
  assert.equal(typeof NS.isJobPage, 'function');
});

test('空快照字段齐全', () => {
  const s = NS.emptySnapshot();
  for (const f of ['jobTitle', 'companyName', 'jobUrl', 'salaryText', 'missingFields']) {
    assert.ok(f in s, `缺 ${f}`);
  }
  // vm 里造的数组是另一个 realm 的，deepStrictEqual 会因为原型不同而失败
  assert.equal(s.missingFields.length, 0);
});

test('文本兜底：能从页面可见文本里抠出薪资/经验/学历/规模', () => {
  const p = NS.TEXT_PATTERNS;
  assert.equal(PAGE_TEXT_SAMPLE.match(p.salaryText)[1], '10-15K·13薪');
  assert.equal(PAGE_TEXT_SAMPLE.match(p.experienceText)[1], '经验不限');
  assert.equal(PAGE_TEXT_SAMPLE.match(p.educationText)[1], '本科');
  assert.equal(PAGE_TEXT_SAMPLE.match(p.companySizeText)[1], '20-99人');
});

test('文本兜底：认得日结和万为单位', () => {
  const p = NS.TEXT_PATTERNS;
  assert.equal('薪资 300-500元/天'.match(p.salaryText)[1], '300-500元/天');
  assert.equal('薪资 1.5-2万'.match(p.salaryText)[1], '1.5-2万');
});

test('文本兜底：学历要求要能区分本科和硕士', () => {
  const p = NS.TEXT_PATTERNS;
  assert.equal('深圳 · 5-10年 · 硕士'.match(p.educationText)[1], '硕士');
  assert.equal('深圳 · 经验不限 · 学历不限'.match(p.educationText)[1], '学历不限');
});

test('选择器表里每个字段都有候选项', () => {
  for (const [field, list] of Object.entries(NS.SELECTORS)) {
    assert.ok(Array.isArray(list) && list.length > 0, `${field} 没有候选选择器`);
  }
});
