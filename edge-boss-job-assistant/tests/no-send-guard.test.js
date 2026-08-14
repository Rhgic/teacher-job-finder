/**
 * 「不许发送」的结构性保证。
 *
 * 只读版和自动投递版的区别不能只靠「我们没写那段代码」，
 * 得靠一个会红的测试。谁哪天顺手在 content script 里写了 .click()，这里先炸。
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(here, '..');

/** 只管 content script：它是唯一能碰到 BOSS 页面的地方。 */
const CONTENT_DIR = path.join(root, 'src/content');

const FORBIDDEN = [
  { re: /\.click\s*\(/, why: '模拟点击宿主页面' },
  { re: /\.submit\s*\(/, why: '提交宿主页面表单' },
  { re: /dispatchEvent\s*\(/, why: '向宿主页面派发事件' },
  { re: /execCommand\s*\(/, why: '用 execCommand 改页面内容' },
  { re: /\.focus\s*\(\s*\)\s*;?\s*[\s\S]{0,80}\.value\s*=/, why: '聚焦后填输入框' },
  { re: /document\.querySelector\([^)]*\)\.value\s*=/, why: '直接给页面输入框赋值' },
  { re: /chrome\.scripting/, why: '动态注入脚本' }
];

function jsFiles(dir) {
  return fs
    .readdirSync(dir)
    .filter((f) => f.endsWith('.js'))
    .map((f) => path.join(dir, f));
}

/**
 * 扫代码之前先把注释去掉。
 * 不然「本文件没有 .click()」这句注释自己就会把测试搞红 —— 第一版就是这么炸的。
 */
function stripComments(src) {
  return src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*$/gm, '$1');
}

function readCode(file) {
  return stripComments(fs.readFileSync(file, 'utf8'));
}

test('content script 里没有任何操作宿主页面的代码', () => {
  const files = jsFiles(CONTENT_DIR);
  assert.ok(files.length >= 3, '没扫到 content script');
  const hits = [];
  for (const file of files) {
    const src = readCode(file);
    for (const { re, why } of FORBIDDEN) {
      const m = src.match(re);
      if (m) hits.push(`${path.basename(file)}: ${why} → ${m[0]}`);
    }
  }
  assert.deepEqual(hits, [], `发现能替用户操作页面的代码：\n${hits.join('\n')}`);
});

test('manifest 权限限制在只读所需范围内', () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(root, 'manifest.json'), 'utf8'));
  const allowed = new Set(['storage']);
  for (const p of manifest.permissions || []) {
    assert.ok(allowed.has(p), `多余权限：${p}`);
  }
  // 这几个是自动投递/定时跟进才需要的，只读版一个都不该有
  for (const p of ['alarms', 'notifications', 'tabs', 'webNavigation', 'declarativeNetRequest', 'cookies']) {
    assert.ok(!(manifest.permissions || []).includes(p), `只读版不该申请 ${p}`);
  }
});

test('后台没有定时任务，不会在你不看着的时候动', () => {
  const bgDir = path.join(root, 'src/background');
  for (const file of jsFiles(bgDir)) {
    const src = readCode(file);
    assert.ok(!/chrome\.alarms/.test(src), `${path.basename(file)} 用了 chrome.alarms`);
  }
});

test('侧边栏渲染外部文本时不使用 innerHTML', () => {
  for (const file of jsFiles(CONTENT_DIR)) {
    const src = readCode(file);
    assert.ok(!/\.innerHTML\s*=/.test(src), `${path.basename(file)} 用了 innerHTML`);
  }
});
