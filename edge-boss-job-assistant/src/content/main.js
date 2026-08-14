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
  let currentSnapshot = null;
  let currentDiagnostics = null;

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
        NS.sidebar.renderDiagnostics(currentDiagnostics, currentSnapshot);
      }
    },
    async onMark(action) {
      if (!currentSnapshot) return;
      const key = jobKeyOf(currentSnapshot);
      const res = await send('MARK_RECORD', { jobKey: key, userAction: action });
      NS.sidebar.setMarkHint(res.ok ? `已记录：${action === 'applied' ? '我投了' : '我跳过'}` : '记录失败');
    }
  };

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
    NS.sidebar.renderResult(res.data, handlers);
  }

  /** 等页面渲染稳定：连续 600ms 没有 DOM 变化就认为可以抓了。 */
  function whenSettled(callback, timeoutMs = 6000) {
    let timer = null;
    const start = Date.now();
    const observer = new MutationObserver(() => {
      clearTimeout(timer);
      if (Date.now() - start > timeoutMs) {
        observer.disconnect();
        callback();
        return;
      }
      timer = setTimeout(finish, 600);
    });
    const finish = () => {
      observer.disconnect();
      clearTimeout(timer);
      callback();
    };
    observer.observe(document.documentElement, { childList: true, subtree: true });
    timer = setTimeout(finish, 600);
    setTimeout(finish, timeoutMs);
  }

  function onLocationChange() {
    const url = location.href.split('?')[0];
    if (url === currentUrl) return;
    currentUrl = url;
    currentSnapshot = null;
    currentDiagnostics = null;
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
