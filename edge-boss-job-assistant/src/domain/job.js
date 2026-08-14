/**
 * 岗位快照的类型约定与字段解析。
 *
 * 快照由 content script 从页面抽取，一旦生成就不再修改（设计文档 §4）。
 * 后续所有判断都只能读快照，不能回头去读 DOM，否则页面一跳转结论就对不上人了。
 */

/** 快照缺这些字段就没法判断，直接报「无法识别」。 */
export const REQUIRED_FIELDS = ['jobTitle', 'companyName', 'jobUrl'];

/**
 * @typedef {Object} JobSnapshot
 * @property {string} jobTitle
 * @property {string} companyName
 * @property {string} jobUrl
 * @property {string} jobDescription
 * @property {string} salaryText     原文，如 "8-13K·13薪"
 * @property {string} cityText
 * @property {string} districtText
 * @property {string} experienceText 原文，如 "1-3年"
 * @property {string} educationText  原文，如 "本科"
 * @property {string} companySizeText 原文，如 "20-99人"
 * @property {string} companyIndustry
 * @property {string} publisherName
 * @property {string} publisherTitle 原文，如 "张三·技术总监"
 * @property {string} publisherActive 原文，如 "刚刚活跃"
 * @property {string[]} tags
 * @property {string[]} missingFields 抽取时没拿到的字段
 * @property {number} capturedAt
 */

export function emptySnapshot() {
  return {
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
  };
}

export function isUsableSnapshot(snapshot) {
  if (!snapshot) return false;
  return REQUIRED_FIELDS.every((f) => String(snapshot[f] || '').trim().length > 0);
}

/**
 * 岗位标识。用 URL 里的岗位 id（BOSS 的 /job_detail/<id>.html），
 * 拿不到就退回 公司+职位 的组合，避免同一岗位重复评估、重复计费。
 */
export function jobKey(snapshot) {
  const url = String(snapshot.jobUrl || '');
  const m = url.match(/job_detail\/([A-Za-z0-9~_-]+)\.html/) || url.match(/[?&]lid=([A-Za-z0-9~_-]+)/);
  if (m) return `job:${m[1]}`;
  return `pair:${normalize(snapshot.companyName)}|${normalize(snapshot.jobTitle)}`;
}

function normalize(s) {
  return String(s || '').replace(/\s+/g, '').toLowerCase();
}

/**
 * 解析薪资文案，统一成「月薪 K」区间。
 * 支持：8-13K、8-13k·13薪、1.5-2万、300-500元/天、面议
 * 日薪/时薪不折算成月薪，只标记出来 —— 日结基本等于外包或临时工。
 * @returns {{min:number|null,max:number|null,unit:'month'|'day'|'hour'|null,months:number|null,negotiable:boolean,raw:string}}
 */
export function parseSalary(text) {
  const raw = String(text || '').trim();
  const out = { min: null, max: null, unit: null, months: null, negotiable: false, raw };
  if (!raw) return out;
  if (/面议|待遇面谈|薪资面议/.test(raw)) {
    out.negotiable = true;
    return out;
  }

  const monthsMatch = raw.match(/[·•·]\s*(\d{2})\s*薪/);
  if (monthsMatch) out.months = Number(monthsMatch[1]);

  // 日薪 / 时薪
  const perDay = raw.match(/(\d+(?:\.\d+)?)\s*[-~到]\s*(\d+(?:\.\d+)?)\s*元?\s*\/?\s*天/);
  if (perDay) {
    out.min = Number(perDay[1]);
    out.max = Number(perDay[2]);
    out.unit = 'day';
    return out;
  }
  const perHour = raw.match(/(\d+(?:\.\d+)?)\s*[-~到]\s*(\d+(?:\.\d+)?)\s*元?\s*\/?\s*(?:小时|时)/);
  if (perHour) {
    out.min = Number(perHour[1]);
    out.max = Number(perHour[2]);
    out.unit = 'hour';
    return out;
  }

  // 万 单位
  const wan = raw.match(/(\d+(?:\.\d+)?)\s*[-~到]\s*(\d+(?:\.\d+)?)\s*万/);
  if (wan) {
    out.min = Number(wan[1]) * 10;
    out.max = Number(wan[2]) * 10;
    out.unit = 'month';
    return out;
  }

  // K 区间
  const range = raw.match(/(\d+(?:\.\d+)?)\s*[kK]?\s*[-~到]\s*(\d+(?:\.\d+)?)\s*[kK]/);
  if (range) {
    out.min = Number(range[1]);
    out.max = Number(range[2]);
    out.unit = 'month';
    return out;
  }

  // 单值 K
  const single = raw.match(/(\d+(?:\.\d+)?)\s*[kK]/);
  if (single) {
    out.min = Number(single[1]);
    out.max = Number(single[1]);
    out.unit = 'month';
    return out;
  }
  return out;
}

/**
 * 解析经验要求，返回岗位要求的「最低年限」。
 * 应届/在校/经验不限 → 0
 * @returns {{minYears:number|null,fresh:boolean,raw:string}}
 */
export function parseExperience(text) {
  const raw = String(text || '').trim();
  const out = { minYears: null, fresh: false, raw };
  if (!raw) return out;
  if (/经验不限|不限经验|应届|在校|实习/.test(raw)) {
    out.minYears = 0;
    out.fresh = true;
    return out;
  }
  if (/(\d+)\s*年以内/.test(raw)) {
    out.minYears = 0;
    return out;
  }
  const range = raw.match(/(\d+)\s*[-~]\s*(\d+)\s*年/);
  if (range) {
    out.minYears = Number(range[1]);
    return out;
  }
  const above = raw.match(/(\d+)\s*年以上/);
  if (above) {
    out.minYears = Number(above[1]);
    return out;
  }
  const single = raw.match(/(\d+)\s*年/);
  if (single) {
    out.minYears = Number(single[1]);
    return out;
  }
  return out;
}

const EDU_RANK = { 不限: 0, 初中: 1, 高中: 2, 中专: 2, 大专: 3, 本科: 4, 硕士: 5, 研究生: 5, 博士: 6 };
export const MY_EDU_RANK = { highschool: 2, college: 3, bachelor: 4, master: 5 };

/** 岗位学历门槛的等级，拿不到返回 null。 */
export function parseEducationRank(text) {
  const raw = String(text || '').trim();
  if (!raw) return null;
  if (/学历不限|不限学历|不限/.test(raw)) return 0;
  for (const [word, rank] of Object.entries(EDU_RANK)) {
    if (raw.includes(word)) return rank;
  }
  return null;
}

/** 公司规模文案归一，返回人数下限，用来和偏好档位比。 */
export function parseCompanySize(text) {
  const raw = String(text || '').trim();
  if (!raw) return null;
  const range = raw.match(/(\d+)\s*[-~]\s*(\d+)\s*人/);
  if (range) return { min: Number(range[1]), max: Number(range[2]), raw };
  const above = raw.match(/(\d+)\s*人以上/);
  if (above) return { min: Number(above[1]), max: Infinity, raw };
  return null;
}
