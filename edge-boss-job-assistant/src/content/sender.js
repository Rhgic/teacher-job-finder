/**
 * 发送器。**整个扩展里唯一允许操作 BOSS 页面的文件。**
 *
 * 这样切是故意的：所有能替你动手的代码集中在一个文件里，
 * 你想审的时候只需要读这一个，不用满仓库找。
 * 测试 `tests/no-send-guard.test.js` 会强制这件事 ——
 * 别的 content script 里出现 .click()/dispatchEvent 就报错。
 *
 * 这里不做任何判断。能不能发是 domain/send-guard.js 说了算，
 * 这个文件只负责「已经批准了，去执行」，以及如实汇报执行结果。
 */

(() => {
  const NS = (globalThis.EBJA = globalThis.EBJA || {});

  /** 页面改版就改这张表。 */
  const SEL = {
    startChat: ['.btn-startchat', 'a.btn-startchat', '.job-banner .btn-startchat', '.op-btn-chat'],
    chatInput: ['#chat-input', 'textarea#chat-input', '.chat-input', '.message-controls textarea', '.input-area textarea'],
    sendButton: ['.btn-send', '.chat-op .btn-send', '.message-controls .btn-send', 'button.submit-btn'],
    /** 出现这些说明触发了平台的安全验证，必须立刻停手。 */
    captcha: ['.geetest_panel', '.captcha-wrap', '.verify-wrap', '#captcha', '.nc-container']
  };

  function findFirst(list, { visibleOnly = false } = {}) {
    for (const sel of list) {
      const el = document.querySelector(sel);
      if (!el) continue;
      // 藏着的输入框不算数：往看不见的框里填字，页面上什么都没发生，
      // 但我们会报「已填入」，比直接失败还坑
      if (visibleOnly && el.offsetParent === null) continue;
      return { el, sel };
    }
    return null;
  }

  /** 页面上有没有安全验证。有就一切免谈。 */
  function hasCaptcha() {
    for (const sel of SEL.captcha) {
      const el = document.querySelector(sel);
      if (el && el.offsetParent !== null) return sel;
    }
    return null;
  }

  /**
   * 给受控输入框赋值。
   * 直接 el.value = x 对 React 无效，框架下一次渲染就把它冲掉，
   * 得走原生 setter 再补一个 input 事件，React 才认。
   */
  function setNativeValue(el, value) {
    const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
    if (setter) setter.call(el, value);
    else el.value = value;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function sleep(ms) {
    return new Promise((r) => setTimeout(r, ms));
  }

  /** 等聊天输入框出现，最多等 timeout 毫秒。 */
  async function waitForInput(timeout = 5000) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      const found = findFirst(SEL.chatInput);
      if (found && found.el.offsetParent !== null) return found;
      await sleep(200);
    }
    return null;
  }

  /**
   * 把招呼语填进输入框，不发送。
   * @returns {Promise<{ok:boolean, reason?:string, selector?:string}>}
   */
  async function fill(text) {
    const captcha = hasCaptcha();
    if (captcha) return { ok: false, reason: `页面出现安全验证（${captcha}），已停手` };

    let input = findFirst(SEL.chatInput, { visibleOnly: true });
    if (!input) {
      // 聊天框还没开（或者还藏着），需要先点「立即沟通」把它唤出来
      const start = findFirst(SEL.startChat, { visibleOnly: true });
      if (!start) return { ok: false, reason: '页面上找不到沟通按钮和可见的聊天输入框' };
      start.el.click();
      input = await waitForInput();
      if (!input) return { ok: false, reason: '点了沟通按钮但聊天输入框没出现' };
    }

    if (hasCaptcha()) return { ok: false, reason: '打开聊天后弹出了安全验证，已停手' };

    input.el.focus();
    setNativeValue(input.el, text);

    // 确认真的填进去了。受控组件可能把值又冲掉
    await sleep(150);
    const actual = String(input.el.value || '');
    if (actual.trim() !== String(text).trim()) {
      return { ok: false, reason: '填进去的内容和预期不一致，可能被页面框架覆盖了', selector: input.sel };
    }
    return { ok: true, selector: input.sel };
  }

  /**
   * 点发送。**调用方必须已经过了 send-guard。这个函数自己不做任何准入判断。**
   * @returns {Promise<{ok:boolean, status:string, reason?:string}>}
   */
  async function clickSend() {
    if (hasCaptcha()) return { ok: false, status: 'captcha', reason: '发送前发现安全验证' };

    const btn = findFirst(SEL.sendButton, { visibleOnly: true });
    if (!btn) return { ok: false, status: 'no_button', reason: '找不到可见的发送按钮' };
    if (btn.el.disabled) return { ok: false, status: 'disabled', reason: '发送按钮是禁用状态' };

    const input = findFirst(SEL.chatInput, { visibleOnly: true });
    const before = String(input?.el?.value || '');

    btn.el.click();
    await sleep(1200);

    if (hasCaptcha()) return { ok: false, status: 'captcha', reason: '点击后弹出安全验证，结果不明' };

    // BOSS 发送成功后会清空输入框。清空了当作成功，没清空当作结果不明。
    const after = String(findFirst(SEL.chatInput, { visibleOnly: true })?.el?.value ?? before);
    if (before && after.trim() === '') return { ok: true, status: 'sent' };

    // 结果不明就是结果不明，不猜也不重试 —— 重试是重复打招呼的头号来源
    return { ok: false, status: 'unknown', reason: '点了发送但没看到输入框被清空，结果待核实，不会重试' };
  }

  /** 自检：报告发送相关的选择器分别命中没有。 */
  function diagnose() {
    const out = {};
    for (const [name, list] of Object.entries(SEL)) {
      const found = findFirst(list);
      out[name] = found ? `css:${found.sel}` : 'MISS';
    }
    return out;
  }

  NS.sender = { fill, clickSend, diagnose, hasCaptcha };
})();
