/**
 * content script 是 classic script，不能 import，所以在 vm 里跑一遍拿到命名空间。
 *
 * 这里测的是「文本兜底」和「站点匹配」两层。
 * CSS 选择器只能对着真站点验 —— 扩展里的「选择器自检」按钮就是干这个的。
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { PAGE_TEXT_SAMPLE } from './fixtures/jobs.js';

const here = path.dirname(fileURLToPath(import.meta.url));

function loadContentScripts(hostname = 'www.zhipin.com') {
  const context = vm.createContext({
    location: { hostname, pathname: '/job_detail/abc.html', href: `https://${hostname}/job_detail/abc.html` },
    document: { querySelector: () => null, querySelectorAll: () => [], title: '' }
  });
  for (const f of ['site-rules.js', 'page-adapter.js']) {
    vm.runInContext(fs.readFileSync(path.join(here, '../src/content', f), 'utf8'), context);
  }
  return context.EBJA;
}

const NS = loadContentScripts();

test('适配器在没有真 DOM 的环境里也能加载', () => {
  assert.ok(NS);
  assert.equal(typeof NS.extractSnapshot, 'function');
  assert.equal(typeof NS.isJobPage, 'function');
  assert.equal(typeof NS.ruleForHost, 'function');
});

test('空快照字段齐全', () => {
  const s = NS.emptySnapshot();
  for (const f of ['jobTitle', 'companyName', 'jobUrl', 'salaryText', 'site', 'missingFields']) {
    assert.ok(f in s, `缺 ${f}`);
  }
  // vm 里造的数组是另一个 realm 的，deepStrictEqual 会因原型不同而失败
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

test('文本兜底：认得出发布者身份，技术线和 HR 都要分得清', () => {
  const p = NS.TEXT_PATTERNS;
  assert.equal('陈某 · 技术负责人 · 刚刚活跃'.match(p.publisherTitle)[1], '技术负责人');
  assert.equal('李某 · HR · 刚刚活跃'.match(p.publisherTitle)[1], 'HR');
  assert.equal('王某 · 招聘经理 · 本周活跃'.match(p.publisherTitle)[1], '招聘经理');
  assert.equal('张某 · 创始人'.match(p.publisherTitle)[1], '创始人');
  assert.equal('刘某 · 技术经理 · 3日内活跃'.match(p.publisherTitle)[1], '技术经理');
});

test('文本兜底：学历要求要能区分本科和硕士', () => {
  const p = NS.TEXT_PATTERNS;
  assert.equal('深圳 · 5-10年 · 硕士'.match(p.educationText)[1], '硕士');
  assert.equal('深圳 · 经验不限 · 学历不限'.match(p.educationText)[1], '学历不限');
});

test('文本兜底：各站薪资写法都认得（合并多平台后新增）', () => {
  const p = NS.TEXT_PATTERNS;
  assert.equal('薪资 1.2万-1.8万'.match(p.salaryText)[1], '1.2万-1.8万');
  assert.equal('薪资 8千-1.2万'.match(p.salaryText)[1], '8千-1.2万');
  assert.equal('10-15K'.match(p.salaryText)[1], '10-15K');
  assert.equal('1.5-2万'.match(p.salaryText)[1], '1.5-2万');
});
