/**
 * BOSS 页面抽取器（设计文档 §4 / §9）。
 *
 * 关于选择器：BOSS 的 class 名会变，写死一套必挂。所以每个字段有三层策略：
 *   1) 候选 CSS 选择器，按顺序试
 *   2) 页面文本正则兜底（薪资、经验、学历、公司规模这类文案格式很固定）
 *   3) meta / document.title 兜底（职位名、公司名）
 * 每个字段都记录「用哪层拿到的」，侧边栏的「选择器自检」按钮会原样显示，
 * 页面改版时你一眼能看出是哪一层塌了，改最上面那张表就行。
 *
 * 这个文件只读 DOM。它不点击、不填表、不提交 —— 全文件没有 .click() 和 .submit()。
 */

(() => {
  const NS = (globalThis.EBJA = globalThis.EBJA || {});

  /** 改版时只改这张表。 */
  const SELECTORS = {
    jobTitle: ['.job-banner .name h1', '.job-banner h1', '.job-primary .name .job-name', '.job-detail h1', 'h1'],
    salaryText: ['.job-banner .salary', '.job-primary .salary', '.salary'],
    jobDescription: [
      '.job-sec-text',
      '.job-detail-section .job-sec-text',
      '.job-detail .text',
      '.detail-content .job-sec .text'
    ],
    companyName: [
      '.job-banner .company-info .name',
      '.sider-company .company-info a',
      '.company-info .name',
      '.job-sec .company-info .name',
      '.business-info .company-name'
    ],
    companyIndustry: ['.sider-company .company-info p', '.company-info .industry'],
    publisherName: ['.job-boss-info .boss-info-attr', '.boss-info .name', '.job-author .name'],
    publisherTitle: ['.job-boss-info .boss-info-attr', '.boss-info .boss-info-attr', '.job-author .job-boss-info'],
    publisherActive: ['.job-boss-info .boss-active-time', '.boss-online-tag', '.boss-active-time'],
    tags: ['.job-tags span', '.job-keyword-list li', '.tag-all span']
  };

  /** 页面里能一眼认出来的文案格式，用于兜底。 */
  const TEXT_PATTERNS = {
    salaryText: /(\d+(?:\.\d+)?\s*[-~]\s*\d+(?:\.\d+)?\s*[kK万](?:[·•·]\s*\d{2}\s*薪)?|\d+\s*[-~]\s*\d+\s*元\s*\/\s*[天时])/,
    experienceText: /(经验不限|在校\/?应届|应届生?|\d+年以内|\d+\s*[-~]\s*\d+\s*年|\d+\s*年以上)/,
    educationText: /(学历不限|初中及以下|中专\/?中技|高中|大专|本科|硕士|博士)/,
    companySizeText: /(\d+\s*[-~]\s*\d+\s*人|\d+\s*人以上|\d+人以下)/
  };

  function textOf(el) {
    if (!el) return '';
    return (el.innerText || el.textContent || '').replace(/ /g, ' ').trim();
  }

  function firstBySelectors(list) {
    for (const sel of list) {
      const el = document.querySelector(sel);
      const t = textOf(el);
      if (t) return { value: t, strategy: `css:${sel}` };
    }
    return null;
  }

  function allBySelectors(list) {
    for (const sel of list) {
      const els = [...document.querySelectorAll(sel)];
      const values = els.map(textOf).filter(Boolean);
      if (values.length) return { value: values, strategy: `css:${sel}` };
    }
    return null;
  }

  /** 在「岗位主区域」的文本里找模式，比全页 body 找准得多。 */
  function scopeText() {
    const scopes = ['.job-banner', '.job-primary', '.job-detail', '.job-box', 'main'];
    for (const sel of scopes) {
      const el = document.querySelector(sel);
      const t = textOf(el);
      if (t.length > 40) return t;
    }
    return textOf(document.body).slice(0, 8000);
  }

  function byPattern(field, scoped) {
    const re = TEXT_PATTERNS[field];
    if (!re) return null;
    const m = scoped.match(re);
    return m ? { value: m[1], strategy: 'text-pattern' } : null;
  }

  function fromMeta() {
    // 「【深圳XX科技招聘AI应用开发工程师】-BOSS直聘」
    const title = document.title || '';
    const m = title.match(/【(.+?)招聘(.+?)】/);
    if (m) return { companyName: m[1].trim(), jobTitle: m[2].trim() };
    const ogTitle = document.querySelector('meta[property="og:title"]')?.content || '';
    const m2 = ogTitle.match(/【(.+?)招聘(.+?)】/);
    if (m2) return { companyName: m2[1].trim(), jobTitle: m2[2].trim() };
    return {};
  }

  function detectCity(scoped) {
    const el = document.querySelector('.job-banner .text-city, .job-primary .job-area, .job-area');
    const t = textOf(el);
    if (t) return { value: t, strategy: 'css:.job-area' };
    const m = scoped.match(/(北京|上海|广州|深圳|杭州|成都|武汉|南京|苏州|东莞|佛山|珠海|厦门|长沙|西安|郑州|重庆|天津|合肥)/);
    return m ? { value: m[1], strategy: 'text-pattern' } : null;
  }

  /**
   * 抽取岗位快照。
   * @returns {{snapshot:object, diagnostics:object}}
   */
  function extractSnapshot() {
    const scoped = scopeText();
    const meta = fromMeta();
    const diagnostics = {};
    const snapshot = NS.emptySnapshot();

    const pick = (field, selectorList, fallbackValue) => {
      const hit = (selectorList && firstBySelectors(selectorList)) || byPattern(field, scoped);
      if (hit) {
        snapshot[field] = hit.value;
        diagnostics[field] = hit.strategy;
        return;
      }
      if (fallbackValue) {
        snapshot[field] = fallbackValue;
        diagnostics[field] = 'meta';
        return;
      }
      diagnostics[field] = 'MISS';
      snapshot.missingFields.push(field);
    };

    pick('jobTitle', SELECTORS.jobTitle, meta.jobTitle);
    pick('companyName', SELECTORS.companyName, meta.companyName);
    pick('salaryText', SELECTORS.salaryText);
    pick('jobDescription', SELECTORS.jobDescription);
    pick('companyIndustry', SELECTORS.companyIndustry);
    pick('publisherTitle', SELECTORS.publisherTitle);
    pick('publisherActive', SELECTORS.publisherActive);
    pick('experienceText', null);
    pick('educationText', null);
    pick('companySizeText', null);

    const city = detectCity(scoped);
    if (city) {
      snapshot.cityText = city.value;
      diagnostics.cityText = city.strategy;
    } else {
      diagnostics.cityText = 'MISS';
      snapshot.missingFields.push('cityText');
    }

    const tags = allBySelectors(SELECTORS.tags);
    if (tags) {
      snapshot.tags = tags.value;
      diagnostics.tags = tags.strategy;
    } else {
      diagnostics.tags = 'MISS';
    }

    snapshot.jobUrl = location.href.split('?')[0];
    if (!snapshot.jobUrl) snapshot.missingFields.push('jobUrl');
    snapshot.capturedAt = Date.now();

    // 快照一旦生成就不许再改，后面所有判断都基于它
    return { snapshot: Object.freeze(snapshot), diagnostics };
  }

  /** 当前页面是不是一个能评估的岗位详情页。 */
  function isJobPage() {
    return /\/job_detail\//.test(location.pathname) || Boolean(document.querySelector('.job-banner, .job-detail'));
  }

  NS.emptySnapshot = () => ({
    jobTitle: '',
    companyName: '',
    jobUrl: '',
    jobDescription: '',
    salaryText: '',
    cityText: '',
    districtText: '',
    experienceText: '',
    educationText: '',
    companySizeText: '',
    companyIndustry: '',
    publisherName: '',
    publisherTitle: '',
    publisherActive: '',
    tags: [],
    missingFields: [],
    capturedAt: 0
  });

  NS.extractSnapshot = extractSnapshot;
  NS.isJobPage = isJobPage;
  NS.SELECTORS = SELECTORS;
  // 暴露出来给 node 测试用：CSS 选择器只能对着真站点验，
  // 但文本兜底这一层可以用 fixture 跑单测。
  NS.TEXT_PATTERNS = TEXT_PATTERNS;
})();
