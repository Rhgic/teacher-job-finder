/**
 * 岗位侧边栏。挂在 Shadow DOM 里，避免和 BOSS 自己的样式互相污染。
 *
 * 安全约定：JD 正文、模型输出、检索摘要都属于外部内容，
 * 一律用 textContent 写入，绝不拼 innerHTML；链接只允许 http(s)。
 * 这个文件里没有任何针对宿主页面的点击或表单操作。
 */

(() => {
  const NS = (globalThis.EBJA = globalThis.EBJA || {});
  const HOST_ID = 'ebja-sidebar-host';

  const LABEL = { apply: '建议投', review: '待定', skip: '别投' };
  const COLOR = { apply: '#1a7f37', review: '#9a6700', skip: '#b42318' };

  function h(tag, attrs = {}, children = []) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === 'class') el.className = v;
      else if (k === 'style') el.setAttribute('style', v);
      else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
      else if (v !== undefined && v !== null) el.setAttribute(k, v);
    }
    for (const c of [].concat(children)) {
      if (c === null || c === undefined || c === false) continue;
      el.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    }
    return el;
  }

  function safeLink(url, text) {
    if (!/^https?:\/\//i.test(String(url || ''))) return h('span', {}, String(text || url || ''));
    return h('a', { href: url, target: '_blank', rel: 'noopener noreferrer' }, String(text || url));
  }

  function ensureHost() {
    let host = document.getElementById(HOST_ID);
    if (host) return host.shadowRoot;
    host = h('div', { id: HOST_ID });
    document.documentElement.appendChild(host);
    const root = host.attachShadow({ mode: 'open' });
    root.appendChild(h('link', { rel: 'stylesheet', href: chrome.runtime.getURL('src/content/sidebar.css') }));
    root.appendChild(h('div', { class: 'panel' }));
    return root;
  }

  function panel(root) {
    return root.querySelector('.panel');
  }

  function clear(el) {
    while (el.firstChild) el.removeChild(el.firstChild);
  }

  function renderLoading(text = '正在评估这个岗位…') {
    const root = ensureHost();
    const p = panel(root);
    clear(p);
    p.appendChild(h('div', { class: 'loading' }, text));
  }

  function renderError(message, onRetry) {
    const root = ensureHost();
    const p = panel(root);
    clear(p);
    p.appendChild(
      h('div', { class: 'error' }, [
        h('div', {}, message),
        h('div', { class: 'actions' }, [h('button', { onclick: onRetry }, '重试')])
      ])
    );
  }

  function section(title, children) {
    const kids = [].concat(children).filter(Boolean);
    if (kids.length === 0) return null;
    return h('div', { class: 'section' }, [h('h4', {}, title), ...kids]);
  }

  function list(items) {
    if (!items || items.length === 0) return null;
    return h('ul', {}, items.map((t) => h('li', {}, String(t))));
  }

  function renderSources(sources) {
    if (!sources || sources.length === 0) return null;
    return sources.map((s) =>
      h('div', { class: 'source' }, [safeLink(s.url, s.url), s.quote ? h('div', { class: 'quote' }, s.quote) : null])
    );
  }

  function renderResult(result, handlers) {
    const root = ensureHost();
    const p = panel(root);
    clear(p);

    if (!result.ok) {
      p.appendChild(
        h('div', { class: 'error' }, [
          h('div', {}, result.message || '无法识别这个页面'),
          result.missingFields?.length
            ? h('div', { class: 'detail' }, `缺失字段：${result.missingFields.join('、')}`)
            : null,
          h('div', { class: 'actions' }, [
            h('button', { onclick: () => handlers.onDiagnose() }, '选择器自检'),
            h('button', { onclick: () => handlers.onRefresh() }, '重新抓取')
          ])
        ])
      );
      return;
    }

    const color = COLOR[result.decision] || '#57606a';

    p.appendChild(
      h('div', { class: 'head' }, [
        h('span', { class: 'badge', style: `background:${color}` }, LABEL[result.decision] || '未知'),
        h('span', { class: 'score', style: `color:${color}` }, [
          String(result.finalScore),
          h('small', {}, ' /100')
        ]),
        h('span', { class: 'spacer' }),
        result.fromCache ? h('span', { class: 'detail' }, '缓存') : null,
        h('button', { class: 'icon-btn', title: '重新评估', onclick: () => handlers.onRefresh(true) }, '↻'),
        h('button', { class: 'icon-btn', title: '收起', onclick: () => handlers.onClose() }, '×')
      ])
    );

    const body = h('div', { class: 'body' });

    body.appendChild(h('div', { class: 'headline' }, result.headline || ''));

    // 招呼语。红灯不生成，绿黄灯都给，但发不发是另一回事
    if (result.greeting) {
      body.appendChild(renderGreeting(result, handlers));
    } else if (result.decision !== 'skip') {
      body.appendChild(
        h('div', { class: 'readonly-note' }, '没能生成招呼语（原因见下方降级说明），这条得你自己写。')
      );
    }

    // 规则分
    const breakdown = (result.ruleScore?.breakdown || []).map((b) =>
      h('div', {}, [
        h('div', { class: 'row' }, [h('span', { class: 'k' }, b.label), h('span', { class: 'v' }, `${b.points}/${b.weight}`)]),
        h('div', { class: 'detail' }, b.detail)
      ])
    );
    const penalties = (result.ruleScore?.penalties || []).map((p2) =>
      h('div', { class: 'row' }, [h('span', { class: 'k' }, p2.reason), h('span', { class: 'v' }, String(p2.points))])
    );
    const sec1 = section(`规则分 ${result.ruleScore?.score ?? '-'}`, [...breakdown, ...penalties]);
    if (sec1) body.appendChild(sec1);

    // 硬筛
    if (result.hardFilter && !result.hardFilter.passed) {
      const sec = section('硬筛未通过', list(result.hardFilter.reasons));
      if (sec) body.appendChild(sec);
    }

    // 模型匹配
    if (result.llmMatch) {
      const m = result.llmMatch;
      const points = (m.matched_points || []).map((mp) =>
        h('li', {}, [h('span', {}, mp.jd_requirement), h('div', { class: 'detail' }, `→ ${mp.my_evidence}`)])
      );
      const sec = section(`模型匹配 ${m.match_score}`, [
        m.summary ? h('div', {}, m.summary) : null,
        points.length ? h('ul', {}, points) : null,
        m.gaps?.length ? h('div', { class: 'detail' }, `缺口：${m.gaps.join('；')}`) : null,
        m.doubts?.length ? h('div', { class: 'note' }, `疑点：${m.doubts.join('；')}`) : null
      ]);
      if (sec) body.appendChild(sec);
    }

    // 背调
    if (result.verification) {
      const v = result.verification;
      const buckets = [
        ['公司业务是否对得上 JD', v.business_match],
        ['发布者是否像技术负责人直招', v.publisher_check],
        ['是否有持续经营迹象', v.going_concern]
      ];
      const children = [];
      for (const [title, b] of buckets) {
        if (!b?.conclusion) continue;
        children.push(h('div', { class: 'bucket-label' }, title));
        children.push(h('div', {}, b.conclusion));
        const srcs = renderSources(b.sources);
        if (srcs) children.push(...srcs);
      }
      const sec = section(`背调结论：${verdictText(v.verdict)}`, children);
      if (sec) body.appendChild(sec);
    }

    // 矛盾
    if (result.conflicts?.length) {
      const items = result.conflicts.map((c) =>
        h('div', { class: `conflict ${c.severity}` }, [
          h('div', {}, `[${c.severity}] ${c.description}`),
          ...(renderSources(c.sources) || [])
        ])
      );
      body.appendChild(section('矛盾点', items));
    }

    // 降级说明
    if (result.notes?.length) {
      body.appendChild(section('降级说明', h('div', { class: 'note' }, result.notes.join('；'))));
    }

    // 人工标记：纯记录，不触发任何页面动作
    body.appendChild(
      h('div', { class: 'actions' }, [
        h('button', { onclick: () => handlers.onMark('applied') }, '我投了'),
        h('button', { onclick: () => handlers.onMark('skipped') }, '我跳过'),
        h('button', { onclick: () => handlers.onDiagnose() }, '选择器自检')
      ])
    );
    body.appendChild(h('div', { class: 'marked', id: 'mark-hint' }, ''));

    p.appendChild(body);
  }

  /**
   * 招呼语区。文本框是可编辑的 —— 模型写的东西你有最终决定权，
   * 改完再填/再发，走的是框里的实际内容，不是模型原稿。
   */
  function renderGreeting(result, handlers) {
    const g = result.greeting;
    const box = h('div', { class: 'greeting' });

    // 理想区间 80–140，超出只是标黄提醒，不拦
    const counterClass = (n) => (n < 80 || n > 140 ? 'counter warn' : 'counter');

    box.appendChild(
      h('div', { class: 'greeting-head' }, [
        h('span', {}, '招呼语'),
        h('span', { class: 'spacer' }),
        h('span', { class: counterClass(g.charCount), id: 'g-count' }, `${g.charCount} 字`)
      ])
    );

    const ta = h('textarea', { class: 'greeting-text', id: 'greeting-text', rows: '5' });
    ta.value = g.greeting;
    ta.addEventListener('input', () => {
      const n = Array.from(ta.value.trim()).length;
      const counter = box.querySelector('#g-count');
      counter.textContent = `${n} 字`;
      counter.className = counterClass(n);
    });
    box.appendChild(ta);

    if (g.jd_point_used) {
      box.appendChild(h('div', { class: 'detail' }, `对上的 JD 要求：${g.jd_point_used}`));
    }
    if (g.fact_used) {
      box.appendChild(h('div', { class: 'detail' }, `引用的项目事实：${g.fact_used}`));
    }
    for (const w of g.warnings || []) {
      box.appendChild(h('div', { class: 'note' }, w));
    }

    const status = h('div', { class: 'send-status', id: 'send-status' }, '');

    const actions = h('div', { class: 'actions' }, [
      h('button', { onclick: () => handlers.onCopy(ta.value) }, '复制'),
      h('button', { onclick: () => handlers.onFill(ta.value) }, '填入输入框'),
      h('button', { class: 'send', onclick: () => handlers.onSend(ta.value) }, '填入并发送')
    ]);

    box.appendChild(actions);
    box.appendChild(status);
    return box;
  }

  function setSendStatus(text, kind = '') {
    const root = document.getElementById(HOST_ID)?.shadowRoot;
    const el = root?.querySelector('#send-status');
    if (!el) return;
    el.textContent = text;
    el.className = `send-status ${kind}`;
  }

  function getGreetingText() {
    const root = document.getElementById(HOST_ID)?.shadowRoot;
    return root?.querySelector('#greeting-text')?.value || '';
  }

  function verdictText(verdict) {
    return { supported: '有公开信息支撑', insufficient: '信息不足', contradicted: '发现矛盾' }[verdict] || verdict;
  }

  function renderDiagnostics(diagnostics, snapshot) {
    const root = ensureHost();
    const p = panel(root);
    const body = p.querySelector('.body') || p;
    const existing = body.querySelector('.diag-section');
    if (existing) existing.remove();

    const lines = Object.entries(diagnostics).map(([field, strategy]) => {
      const value = String(snapshot[field] ?? '');
      const shown = Array.isArray(snapshot[field]) ? snapshot[field].join(' / ') : value;
      const row = h('div', {}, [
        h('span', strategy === 'MISS' ? { class: 'miss' } : {}, `${field}: ${strategy}`),
        h('span', {}, shown ? `  ← ${shown.slice(0, 60)}` : '')
      ]);
      return row;
    });
    const sec = section('选择器自检', h('div', { class: 'diag' }, lines));
    sec.classList.add('diag-section');
    body.appendChild(sec);
  }

  function setMarkHint(text) {
    const root = document.getElementById(HOST_ID)?.shadowRoot;
    const el = root?.getElementById?.('mark-hint') || root?.querySelector('#mark-hint');
    if (el) el.textContent = text;
  }

  function remove() {
    document.getElementById(HOST_ID)?.remove();
  }

  NS.sidebar = {
    renderLoading,
    renderError,
    renderResult,
    renderDiagnostics,
    setMarkHint,
    setSendStatus,
    getGreetingText,
    remove
  };
})();
