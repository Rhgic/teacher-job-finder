/**
 * 招呼语校验（设计文档 §5.1 / §8）。
 *
 * 模型写完不算数，得过这一关。这里挡的不是文笔，是三种会让你在面试当场下不来台的东西：
 *   1. 编数字 —— 事实库里没有任何指标，招呼语里冒出「准确率 95%」就是幻觉
 *   2. 编经历 —— 提到事实库里不存在的项目
 *   3. 说空话 —— 「贵司前景广阔」，发了等于没发
 *
 * 校验不过就不给发，转人工改。
 */

export const MIN_CHARS = 60;
export const MAX_CHARS = 160;
/** 设计文档要求 80–140，这是理想区间；超出但没到硬上限只警告。 */
export const IDEAL_MIN = 80;
export const IDEAL_MAX = 140;

/** 发出去等于没发的套话。 */
const FILLER_PATTERNS = [
  /贵[司公][前发]/,
  /前景[广远]/,
  /深受启发/,
  /一直(很)?关注贵/,
  /仰慕/,
  /久仰/,
  /恳请/,
  /万分(感谢|荣幸)/,
  /希望能有机会加入贵/
];

/** 量化结果的写法。事实库里一个指标都没有，所以这些一律视为编的。 */
const METRIC_PATTERNS = [
  /\d+\s*%/,
  /\d+\s*(条|万|亿|倍|人次|用户|QPS|qps)/,
  /准确率|召回率|自动解决率|命中率|提升了|降低了/
];

const PLACEHOLDER_PATTERNS = [/[【】]/, /\{\{.*?\}\}/, /\[.*?\]/, /XX+/, /某某/];

export function charCount(text) {
  return Array.from(String(text || '').trim()).length;
}

/**
 * 把事实库摊平成「允许出现的锚点词」。
 * 招呼语至少要命中一个，否则说明它没引用任何真实项目。
 */
export function factAnchors(facts) {
  const anchors = new Set();
  for (const f of facts || []) {
    if (f.project) anchors.add(f.project);
    for (const c of f.claims || []) {
      // 从事实描述里抠出技术名词当锚点
      const tokens = String(c.text || '').match(/[A-Za-z][A-Za-z.\s]{2,20}[A-Za-z]|[一-龥]{2,8}/g) || [];
      for (const t of tokens) {
        const s = t.trim();
        if (s.length >= 2) anchors.add(s);
      }
    }
  }
  return [...anchors];
}

/**
 * @returns {{ok:boolean, errors:string[], warnings:string[], charCount:number}}
 */
export function validateGreeting(text, profile) {
  const errors = [];
  const warnings = [];
  const raw = String(text || '').trim();
  const n = charCount(raw);

  if (!raw) {
    return { ok: false, errors: ['招呼语为空'], warnings: [], charCount: 0 };
  }
  if (n < MIN_CHARS) errors.push(`只有 ${n} 字，太短`);
  if (n > MAX_CHARS) errors.push(`${n} 字，超过上限 ${MAX_CHARS}`);
  if (n >= MIN_CHARS && n < IDEAL_MIN) warnings.push(`${n} 字，低于理想区间 ${IDEAL_MIN}–${IDEAL_MAX}`);
  if (n <= MAX_CHARS && n > IDEAL_MAX) warnings.push(`${n} 字，超出理想区间 ${IDEAL_MIN}–${IDEAL_MAX}`);

  if (/\n/.test(raw)) warnings.push('含换行，BOSS 输入框里会被压成一行');

  for (const re of FILLER_PATTERNS) {
    const m = raw.match(re);
    if (m) errors.push(`含套话「${m[0]}」`);
  }

  for (const re of METRIC_PATTERNS) {
    const m = raw.match(re);
    if (m) errors.push(`出现未经证实的量化说法「${m[0]}」，事实库里没有任何指标`);
  }

  for (const re of PLACEHOLDER_PATTERNS) {
    const m = raw.match(re);
    if (m) errors.push(`含占位符或模板残留「${m[0]}」`);
  }

  // 至少命中一个事实库锚点
  const anchors = factAnchors(profile.facts);
  const hit = anchors.filter((a) => raw.includes(a));
  if (hit.length === 0) {
    errors.push('没有引用任何事实库里的项目或技术，等于没说自己会什么');
  }

  return { ok: errors.length === 0, errors, warnings, charCount: n, anchorsHit: hit.slice(0, 5) };
}

/** 模型返回的结构校验，和 schema.js 的风格一致：坏了就转人工，不修补。 */
export function validateGreetingPayload(raw, profile) {
  if (!raw || typeof raw !== 'object') return { ok: false, value: null, errors: ['不是对象'] };
  const greeting = typeof raw.greeting === 'string' ? raw.greeting.trim() : '';
  const check = validateGreeting(greeting, profile);
  if (!check.ok) return { ok: false, value: null, errors: check.errors };

  const factUsed = typeof raw.fact_used === 'string' ? raw.fact_used.trim() : '';
  return {
    ok: true,
    errors: [],
    warnings: check.warnings,
    value: {
      greeting,
      jd_point_used: typeof raw.jd_point_used === 'string' ? raw.jd_point_used.trim() : '',
      fact_used: factUsed,
      charCount: check.charCount,
      anchorsHit: check.anchorsHit
    }
  };
}
