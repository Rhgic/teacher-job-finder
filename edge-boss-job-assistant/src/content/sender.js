/**
 * 发送器。**整个扩展里唯一允许操作页面的文件。**
 *
 * 这样切是故意的：所有能替你动手的代码集中在一个文件里，
 * 你想审的时候只需要读这一个。`tests/no-send-guard.test.js` 会强制这件事。
 *
 * 这里不做任何判断。能不能发是 domain/send-guard.js 说了算，
 * 这个文件只负责「已经批准了，去执行」，以及如实汇报执行结果。
 *
 * 找元素的策略（合并 edge-job-assistant 的做法后改的）：
 *   1) 站点规则里的 class 快路径，命中就用
 *   2) 命中不了就扫全页按钮，按文案匹配（「立即沟通」「发送」）
 * 第 2 层才是主力 —— class 名会变，按钮上的字不会。
 */

(() => {
  const NS = (globalThis.EBJA = globalThis.EBJA || {});

  const CLICKABLE = 'button, [role="button"], a, input[type="submit"], input[type="button"], .btn';

  function rule() {
    return NS.currentRule?.() || null;
  }

  function isVisible(el) {
    if (!el) return false;
    if (el.offsetParent === null && getComputedStyle(el).position !== 'fixed') return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }

  function textOf(el) {
    return (el.innerText || el.textContent || el.value || '').replace(/\s+/g, '').trim();
  }

  function bySelectors(list) {
    for (const sel of list || []) {
      const el = document.querySelector(sel);
      if (el && isVisible(el)) return { el, how: `css:${sel}` };
    }
    return null;
  }

  /**
   * 按文案找可点元素。
   * 取最短匹配文本的那个：「立即沟通」按钮的文字就是「立即沟通」，
   * 而包着它的某个 div 可能整段文字都含这四个字，取短的才不会点到外面的容器。
   */
  function byKeywords(keywords) {
    const candidates = [];
    for (const el of document.querySelectorAll(CLICKABLE)) {
      if (!isVisible(el)) continue;
      if (el.disabled) continue;
      const t = textOf(el);
      if (!t || t.length > 20) continue;
      const hit = (keywords || []).find((k) => t.includes(k.replace(/\s+/g, '')));
      if (hit) candidates.push({ el, how: `text:${hit}`, len: t.length });
    }
    if (candidates.length === 0) return null;
    candidates.sort((a, b) => a.len - b.len);
    return candidates[0];
  }

  function findAction(kind) {
    const r = rule();
    if (!r) return null;
    const selectors = kind === 'send' ? r.sendSelectors : r.startChatSelectors;
    const keywords = kind === 'send' ? r.sendKeywords : r.startChatKeywords;
    return bySelectors(selectors) || byKeywords(keywords);
  }

  function findEditor() {
    const r = rule();
    for (const sel of r?.editorSelectors || NS.COMMON_EDITORS || []) {
      for (const el of document.querySelectorAll(sel)) {
        if (isVisible(el) && !el.readOnly && !el.disabled) return { el, how: `css:${sel}` };
      }
    }
    return null;
  }

  /** 页面上有没有安全验证。有就一切免谈。 */
  function hasCaptcha() {
    for (const sel of NS.COMMON_CAPTCHA || []) {
      const el = document.querySelector(sel);
      if (el && isVisible(el)) return sel;
    }
    return null;
  }

  /**
   * 给输入框赋值。
   * 直接 el.value = x 对 React 无效，框架下一次渲染就冲掉，得走原生 setter 再补事件。
   * contenteditable 走 textContent，两种编辑器都要支持。
   */
  function setEditorValue(el, value) {
    if (el.isContentEditable) {
      el.focus();
      el.textContent = value;
      el.dispatchEvent(new InputEvent('input', { bubbles: true, data: value }));
      return;
    }
    const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
    if (setter) setter.call(el, value);
    else el.value = value;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function readEditor(el) {
    return el.isContentEditable ? String(el.textContent || '') : String(el.value || '');
  }

  function sleep(ms) {
    return new Promise((r) => setTimeout(r, ms));
  }

  async function waitForEditor(timeout = 5000) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      const found = findEditor();
      if (found) return found;
      await sleep(200);
    }
    return null;
  }

  /**
   * 把招呼语填进输入框，不发送。
   * @returns {Promise<{ok:boolean, reason?:string, how?:string}>}
   */
  async function fill(text) {
    if (!rule()) return { ok: false, reason: '当前站点不在支持列表里' };
    const captcha = hasCaptcha();
    if (captcha) return { ok: false, reason: `页面出现安全验证（${captcha}），已停手` };

    let editor = findEditor();
    if (!editor) {
      // 聊天框还没开，先把它唤出来
      const start = findAction('start');
      if (!start) return { ok: false, reason: '找不到沟通按钮，也找不到可见的输入框' };
      start.el.click();
      editor = await waitForEditor();
      if (!editor) return { ok: false, reason: '点了沟通按钮但输入框没出现' };
    }

    if (hasCaptcha()) return { ok: false, reason: '打开聊天后弹出了安全验证，已停手' };

    editor.el.focus();
    setEditorValue(editor.el, text);

    await sleep(150);
    if (readEditor(editor.el).trim() !== String(text).trim()) {
      return { ok: false, reason: '填进去的内容和预期不一致，可能被页面框架覆盖了', how: editor.how };
    }
    return { ok: true, how: editor.how };
  }

  /**
   * 点发送。**调用方必须已经过了 send-guard，这里不做任何准入判断。**
   * @returns {Promise<{ok:boolean, status:string, reason?:string}>}
   */
  async function clickSend() {
    if (hasCaptcha()) return { ok: false, status: 'captcha', reason: '发送前发现安全验证' };

    const btn = findAction('send');
    if (!btn) return { ok: false, status: 'no_button', reason: '找不到可见的发送按钮' };

    const editor = findEditor();
    const before = editor ? readEditor(editor.el) : '';

    btn.el.click();
    await sleep(1200);

    if (hasCaptcha()) return { ok: false, status: 'captcha', reason: '点击后弹出安全验证，结果不明' };

    // 发送成功后输入框会被清空。清空了当作成功，没清空当作结果不明。
    const nowEditor = findEditor();
    const after = nowEditor ? readEditor(nowEditor.el) : '';
    if (before && after.trim() === '') return { ok: true, status: 'sent' };

    // 结果不明就是结果不明，不猜也不重试 —— 重试是重复打招呼的头号来源
    return { ok: false, status: 'unknown', reason: '点了发送但没看到输入框被清空，结果待核实，不会重试' };
  }

  /** 自检：报告发送相关的元素分别是怎么找到的。 */
  function diagnose() {
    const r = rule();
    const start = findAction('start');
    const send = findAction('send');
    const editor = findEditor();
    return {
      站点: r ? `${r.label}(${r.key})` : 'MISS',
      沟通按钮: start ? start.how : 'MISS',
      输入框: editor ? editor.how : 'MISS',
      发送按钮: send ? send.how : 'MISS',
      安全验证: hasCaptcha() || '无'
    };
  }

  NS.sender = { fill, clickSend, diagnose, hasCaptcha };
})();
