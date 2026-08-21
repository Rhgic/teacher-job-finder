/**
 * 模型输出的结构校验（设计文档 §8）。
 *
 * 校验失败不重试、不猜测、不「尽力解析」，直接转人工。
 * 模型幻觉在这一层拦住，比在侧边栏上写免责声明有用得多。
 *
 * 零依赖，所以手写校验；规则很少，够用。
 */

const SEVERITIES = new Set(['high', 'medium', 'low']);
const VERDICTS = new Set(['supported', 'insufficient', 'contradicted']);

function str(v) {
  return typeof v === 'string' ? v.trim() : '';
}

function arr(v) {
  return Array.isArray(v) ? v : [];
}

/** 只保留带合法 http(s) URL 且有摘录的来源，其余丢弃。 */
function cleanSources(v, allowedUrls) {
  return arr(v)
    .map((s) => ({ url: str(s?.url), quote: str(s?.quote) }))
    .filter((s) => {
      if (!/^https?:\/\//i.test(s.url)) return false;
      // 模型只能引用我们喂进去的检索结果，不许自己编 URL
      if (allowedUrls && !allowedUrls.has(normalizeUrl(s.url))) return false;
      return s.quote.length > 0;
    });
}

export function normalizeUrl(u) {
  try {
    const url = new URL(u);
    return `${url.origin}${url.pathname}`.replace(/\/$/, '').toLowerCase();
  } catch {
    return String(u || '').toLowerCase();
  }
}

/**
 * 岗位匹配结果。
 * @returns {{ok:boolean, value:object|null, errors:string[]}}
 */
export function validateMatch(raw) {
  const errors = [];
  if (!raw || typeof raw !== 'object') return { ok: false, value: null, errors: ['不是对象'] };

  const score = Number(raw.match_score);
  if (!Number.isFinite(score) || score < 0 || score > 100) errors.push('match_score 不是 0-100 的数字');

  const matched = arr(raw.matched_points)
    .map((p) => ({
      jd_requirement: str(p?.jd_requirement),
      my_evidence: str(p?.my_evidence),
      evidence_source: str(p?.evidence_source)
    }))
    .filter((p) => p.jd_requirement && p.my_evidence);

  const summary = str(raw.summary);
  if (!summary) errors.push('summary 为空');

  if (errors.length) return { ok: false, value: null, errors };

  return {
    ok: true,
    errors: [],
    value: {
      match_score: Math.round(score),
      matched_points: matched,
      gaps: arr(raw.gaps).map(str).filter(Boolean),
      doubts: arr(raw.doubts).map(str).filter(Boolean),
      summary,
      preference_positive: cleanPreferenceItems(raw.preference_positive),
      preference_negative: cleanPreferenceItems(raw.preference_negative)
    }
  };
}

/**
 * 偏好命中项。这里只做形状清洗，「这条是不是用户真配过」由 domain/preference.js 判，
 * 因为只有那边拿得到配置。
 */
function cleanPreferenceItems(v) {
  return arr(v)
    .map((p) => ({
      item: str(p?.item),
      reason: str(p?.reason),
      score: Number.isFinite(Number(p?.score)) ? Math.max(0, Math.round(Number(p.score))) : 0
    }))
    .filter((p) => p.item);
}

/**
 * 公开信息背调结果。
 * @param {object} raw 模型原始输出
 * @param {string[]} allowedUrlList 检索结果里真实存在的 URL；模型引用范围只能是它
 */
export function validateVerification(raw, allowedUrlList = []) {
  const errors = [];
  if (!raw || typeof raw !== 'object') return { ok: false, value: null, errors: ['不是对象'] };

  const allowed = allowedUrlList.length ? new Set(allowedUrlList.map(normalizeUrl)) : null;

  const bucket = (b) => {
    const conclusion = str(b?.conclusion);
    const sources = cleanSources(b?.sources, allowed);
    // 没有来源的结论不算结论，降级为「信息不足」
    if (conclusion && sources.length === 0) {
      return { conclusion: '信息不足：模型没有给出可核验来源', sources: [], grounded: false };
    }
    return { conclusion, sources, grounded: sources.length > 0 };
  };

  const business_match = bucket(raw.business_match);
  const publisher_check = bucket(raw.publisher_check);
  const going_concern = bucket(raw.going_concern);

  const conflicts = arr(raw.consistency_conflicts)
    .map((c) => ({
      severity: SEVERITIES.has(str(c?.severity)) ? str(c.severity) : 'low',
      description: str(c?.description),
      sources: cleanSources(c?.sources, allowed)
    }))
    .filter((c) => c.description)
    // 没有来源撑着的「高风险」降为中风险：宁可标黄让人看，也不要靠幻觉把好岗位毙掉
    .map((c) => (c.severity === 'high' && c.sources.length === 0 ? { ...c, severity: 'medium', description: `${c.description}（无来源支撑，已降级）` } : c));

  let verdict = str(raw.verdict);
  if (!VERDICTS.has(verdict)) verdict = 'insufficient';
  const grounded = business_match.grounded || publisher_check.grounded || going_concern.grounded;
  if (verdict === 'supported' && !grounded) verdict = 'insufficient';
  if (conflicts.some((c) => c.severity === 'high')) verdict = 'contradicted';

  const summary = str(raw.summary) || '背调信息不足';

  if (errors.length) return { ok: false, value: null, errors };

  return {
    ok: true,
    errors: [],
    value: { verdict, business_match, publisher_check, going_concern, consistency_conflicts: conflicts, summary }
  };
}

/**
 * 从模型返回的文本里取 JSON。
 * 只做一件事：剥掉 ```json 围栏。取不到就失败，不做花式修补。
 */
export function parseJsonStrict(text) {
  const raw = String(text || '').trim();
  const fenced = raw.match(/```(?:json)?\s*([\s\S]*?)```/i);
  const body = fenced ? fenced[1].trim() : raw;
  try {
    return { ok: true, value: JSON.parse(body), error: null };
  } catch (e) {
    return { ok: false, value: null, error: e.message };
  }
}
