/**
 * Content script 入口。
 *
 * 生命周期：进到岗位详情页 → 等 DOM 稳定 → 抽快照 → 让后台评估 → 渲染侧边栏。
 * URL 变了就重来一遍。除此之外它什么都不做。
 *
 * 这个文件不会向宿主页面派发任何事件、不点击、不填表。
 */

(() => {
  const NS = globalThis.EBJA;
  if (!NS || NS.__started) return;
  NS.__started = true;

  let currentUrl = '';
  let currentIdentity = '';
  let currentSnapshot = null;
  let currentDiagnostics = null;
  let currentResult = null;

  function send(type, payload) {
    return new Promise((resolve) => {
      chrome.runtime.sendMessage({ type, payload }, (res) => {
        if (chrome.runtime.lastError) {
          resolve({ ok: false, error: chrome.runtime.lastError.message });
          return;
        }
        resolve(res || { ok: false, error: '后台没有响应' });
      });
    });
  }

  const handlers = {
    onRefresh(force = false) {
      run({ force: Boolean(force), fresh: true });
    },
    onClose() {
      NS.sidebar.remove();
    },
    onDiagnose() {
      if (currentDiagnostics && currentSnapshot) {
        NS.sidebar.renderDiagnostics(
          { ...currentDiagnostics, ...prefix(NS.sender.diagnose(), '[发送]') },
          currentSnapshot
        );
      }
    },
    async onMark(action) {
      if (!currentSnapshot) return;
      const key = jobKeyOf(currentSnapshot);
      const res = await send('MARK_RECORD', { jobKey: key, userAction: action });
      NS.sidebar.setMarkHint(res.ok ? `已记录：${action === 'applied' ? '我投了' : '我跳过'}` : '记录失败');
    },
    async onCopy(text) {
      try {
        await navigator.clipboard.writeText(text);
        NS.sidebar.setSendStatus('已复制', 'ok');
      } catch {
        NS.sidebar.setSendStatus('复制失败，手动选中吧', 'err');
      }
    },
    // 「填入」也要过闸。BOSS 上要填招呼语得先点开聊天窗，
    // 而点开聊天窗本身在平台口径里就已经算「打过招呼」了 ——
    // 所以它和发送一样要查去重、查日上限、查页面有没有翻走。
    onFill(text) {
      return doSend(text, { auto: false, forceFillOnly: true });
    },
    onSend(text) {
      return doSend(text, { auto: false });
    }
  };

  function prefix(obj, tag) {
    return Object.fromEntries(Object.entries(obj).map(([k, v]) => [`${tag}${k}`, v]));
  }

  /**
   * 发送流程。顺序是刻意的：
   *   重抓页面 → 后台过闸（含去重、限额、页面一致性）→ 后台先记账 → 才填 → 才点。
   * 先记账后点击，是因为「记了但没发」只损失一个岗位，
   * 「发了没记」会导致重复打招呼，那个更难收场。
   */
  async function doSend(text, { auto, forceFillOnly = false }) {
    if (!currentResult || !currentSnapshot) return;

    NS.sidebar.setSendStatus(auto ? '自动发送：正在核对…' : '正在核对…');

    // 发送这一刻重新读页面，确认还站在同一个岗位上
    const { snapshot: pageSnapshot } = NS.extractSnapshot();

    const check = await send('CHECK_SEND', {
      jobKey: jobKeyOf(currentSnapshot),
      snapshot: currentSnapshot,
      pageSnapshot,
      greeting: text,
      decision: currentResult.decision,
      auto
    });

    if (!check.ok) {
      NS.sidebar.setSendStatus(`核对失败：${check.error}`, 'err');
      return;
    }
    if (!check.data.allowed) {
      NS.sidebar.setSendStatus(`没发：${check.data.reasons.join('；')}`, 'blocked');
      return;
    }

    NS.sidebar.setSendStatus('正在填入…');
    const filled = await NS.sender.fill(text);
    if (!filled.ok) {
      await send('CONFIRM_SENT', { jobKey: jobKeyOf(currentSnapshot), status: 'fill_failed', reason: filled.reason });
      NS.sidebar.setSendStatus(`填入失败，没有发送：${filled.reason}`, 'err');
      return;
    }

    if (forceFillOnly || check.data.fillOnly) {
      await send('CONFIRM_SENT', { jobKey: jobKeyOf(currentSnapshot), status: 'filled_only' });
      NS.sidebar.setSendStatus(
        forceFillOnly ? '已填进输入框，发送键你自己按。' : '已填进输入框。自动发送是关的，发送键你自己按。',
        'ok'
      );
      return;
    }

    NS.sidebar.setSendStatus('正在发送…');
    const sent = await NS.sender.clickSend();
    await send('CONFIRM_SENT', {
      jobKey: jobKeyOf(currentSnapshot),
      status: sent.status,
      reason: sent.reason || ''
    });

    if (sent.ok) NS.sidebar.setSendStatus('已发送', 'ok');
    else if (sent.status === 'unknown') NS.sidebar.setSendStatus(`结果待核实：${sent.reason}`, 'blocked');
    else NS.sidebar.setSendStatus(`没发出去：${sent.reason}`, 'err');
  }

  /** 和 domain/job.js 的 jobKey 保持一致；content script 不加载 ES module，所以这里重写一份。 */
  function jobKeyOf(snapshot) {
    const url = String(snapshot.jobUrl || '');
    const m = url.match(/job_detail\/([A-Za-z0-9~_-]+)\.html/) || url.match(/[?&]lid=([A-Za-z0-9~_-]+)/);
    if (m) return `job:${m[1]}`;
    const norm = (s) => String(s || '').replace(/\s+/g, '').toLowerCase();
    return `pair:${norm(snapshot.companyName)}|${norm(snapshot.jobTitle)}`;
  }

  async function run({ force = false, fresh = false } = {}) {
    if (!NS.isJobPage()) {
      NS.sidebar.remove();
      return;
    }

    if (fresh || !currentSnapshot) {
      const { snapshot, diagnostics } = NS.extractSnapshot();
      currentSnapshot = snapshot;
      currentDiagnostics = diagnostics;
    }

    if (!currentSnapshot.jobTitle || !currentSnapshot.companyName) {
      NS.sidebar.renderResult(
        {
          ok: false,
          message: '页面结构不认识，没抓到职位名或公司名。点「选择器自检」看是哪一层塌了。',
          missingFields: currentSnapshot.missingFields
        },
        handlers
      );
      return;
    }

    NS.sidebar.renderLoading();
    const res = await send('EVALUATE_JOB', { snapshot: currentSnapshot, force });
    if (!res.ok) {
      NS.sidebar.renderError(`评估失败：${res.error}`, () => run({ force: true, fresh: true }));
      return;
    }
    currentResult = res.data;
    NS.sidebar.renderResult(res.data, handlers);

    // 自动发送：只有绿灯、开关开着、且岗位有招呼语时才走。
    // 闸门在后台，这里请求一次，被拒就只是在侧边栏写一行原因。
    if (res.data.decision === 'apply' && res.data.greeting) {
      const state = await send('GET_SEND_CONFIG');
      if (state.ok && state.data.autoSend && !state.data.fillOnly) {
        await doSend(res.data.greeting.greeting, { auto: true });
      }
    }
  }

  /**
   * 等页面渲染稳定：连续 600ms 没有 DOM 变化就认为可以抓了。
   *
   * done 这个标志是必须的。这里有两个定时器（防抖的和兜底的），
   * 少了它两个都会触发，一个岗位被评估两遍 —— 缓存能挡住重复计费，
   * 但挡不住自动发送被触发两次。
   */
  function whenSettled(callback, timeoutMs = 6000) {
    let timer = null;
    let hardTimer = null;
    let done = false;

    const finish = () => {
      if (done) return;
      done = true;
      observer.disconnect();
      clearTimeout(timer);
      clearTimeout(hardTimer);
      callback();
    };

    const observer = new MutationObserver(() => {
      if (done) return;
      clearTimeout(timer);
      timer = setTimeout(finish, 600);
    });

    observer.observe(document.documentElement, { childList: true, subtree: true });
    timer = setTimeout(finish, 600);
    hardTimer = setTimeout(finish, timeoutMs);
  }

  /**
   * 页面换没换。URL 和「当前是哪个岗位」两个信号都看，任一变化就重来。
   * 只看 URL 会漏掉 BOSS 原地换岗位内容的情况，那种情况下
   * 你会拿着上一个岗位的分数和招呼语去投这一个。
   */
  function onLocationChange() {
    const url = location.href.split('?')[0];
    const identity = NS.isJobPage() ? NS.pageIdentity() : '';
    if (url === currentUrl && identity === currentIdentity) return;

    currentUrl = url;
    currentIdentity = identity;
    currentSnapshot = null;
    currentDiagnostics = null;
    currentResult = null;
    NS.sidebar.remove();
    whenSettled(() => run({ fresh: true }));
  }

  // BOSS 有前端路由，history API 和轮询都盯上
  for (const method of ['pushState', 'replaceState']) {
    const original = history[method];
    history[method] = function (...args) {
      const ret = original.apply(this, args);
      queueMicrotask(onLocationChange);
      return ret;
    };
  }
  window.addEventListener('popstate', onLocationChange);
  setInterval(onLocationChange, 1500);

  onLocationChange();
})();
