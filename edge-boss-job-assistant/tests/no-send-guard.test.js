/**
 * 「谁能碰页面」的结构性保证。
 *
 * 扩展现在会发东西了，所以规则从「谁都不许碰」改成「只有一个文件能碰」。
 * 意义没变：想审风险的时候只需要读 sender.js 一个文件，
 * 别的地方冒出 .click() 这里就红。
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(here, '..');
const CONTENT_DIR = path.join(root, 'src/content');

/** 唯一允许操作宿主页面的文件。 */
const SENDER = 'sender.js';

const PAGE_ACTION_PATTERNS = [
  { re: /\.click\s*\(/, why: '模拟点击宿主页面' },
  { re: /\.submit\s*\(/, why: '提交宿主页面表单' },
  { re: /dispatchEvent\s*\(/, why: '向宿主页面派发事件' },
  { re: /execCommand\s*\(/, why: '用 execCommand 改页面内容' },
  // 只盯「往页面上找到的元素里塞值」。侧边栏给自己 shadow DOM 里的
  // textarea 赋值是正常的，不该算在内
  { re: /setNativeValue/, why: '走原生 setter 给受控输入框赋值' },
  { re: /querySelector\([^)]*\)\s*\.\s*value\s*=/, why: '直接给页面上查到的元素赋值' }
];

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

function jsFiles(dir) {
  return fs
    .readdirSync(dir)
    .filter((f) => f.endsWith('.js'))
    .map((f) => path.join(dir, f));
}

test('除 sender.js 外，没有 content script 能操作宿主页面', () => {
  const files = jsFiles(CONTENT_DIR).filter((f) => path.basename(f) !== SENDER);
  assert.ok(files.length >= 3, '没扫到 content script');
  const hits = [];
  for (const file of files) {
    const src = readCode(file);
    for (const { re, why } of PAGE_ACTION_PATTERNS) {
      const m = src.match(re);
      if (m) hits.push(`${path.basename(file)}: ${why} → ${m[0].trim()}`);
    }
  }
  assert.deepEqual(hits, [], `这些操作只能写在 ${SENDER} 里：\n${hits.join('\n')}`);
});

test('sender.js 自己不做准入判断，必须由 send-guard 放行', () => {
  const src = readCode(path.join(CONTENT_DIR, SENDER));
  // 发送器里不该出现任何配额、去重、决策相关的判断
  for (const forbidden of [/dailySendLimit/, /wasSent/, /decision\s*===/, /autoSend/]) {
    assert.ok(!forbidden.test(src), `sender.js 里不该有准入判断：${forbidden}`);
  }
});

test('发送前必须过闸：main.js 里 CHECK_SEND 出现在 sender 调用之前', () => {
  const src = readCode(path.join(CONTENT_DIR, 'main.js'));
  const check = src.indexOf('CHECK_SEND');
  const fill = src.indexOf('NS.sender.fill');
  const click = src.indexOf('NS.sender.clickSend');
  assert.ok(check > -1, 'main.js 没有调用 CHECK_SEND');
  assert.ok(fill > check, '填入发生在过闸之前');
  assert.ok(click > check, '点击发生在过闸之前');
});

test('sender.js 不重试', () => {
  const src = readCode(path.join(CONTENT_DIR, SENDER));
  assert.ok(!/for\s*\(.*retry|while\s*\(.*retry|retries|maxAttempts/i.test(src), 'sender.js 里出现了重试逻辑');
});

test('manifest 权限限制在必要范围内', () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(root, 'manifest.json'), 'utf8'));
  const allowed = new Set(['storage']);
  for (const p of manifest.permissions || []) {
    assert.ok(allowed.has(p), `多余权限：${p}`);
  }
  for (const p of ['alarms', 'notifications', 'tabs', 'webNavigation', 'declarativeNetRequest', 'cookies']) {
    assert.ok(!(manifest.permissions || []).includes(p), `不该申请 ${p}`);
  }
});

test('后台没有定时任务，不会在你不看着的时候自己发', () => {
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

test('自动发送默认关闭', () => {
  const src = fs.readFileSync(path.join(root, 'src/storage/store.js'), 'utf8');
  const block = src.match(/DEFAULT_SEND_CONFIG\s*=\s*\{[\s\S]*?\n\};/);
  assert.ok(block, '找不到 DEFAULT_SEND_CONFIG');
  assert.match(block[0], /autoSend:\s*false/, '自动发送默认必须是关的');
  assert.match(block[0], /fillOnly:\s*true/, '默认必须是只填不发');
  assert.match(block[0], /allowReviewSend:\s*false/, '黄灯岗位默认不许自动发');
});
