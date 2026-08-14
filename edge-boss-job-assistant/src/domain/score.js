/**
 * 第二层：规则打分（设计文档 §4.1）。
 *
 * 规则分是「不联网也能给出的判断」，模型不可用时直接拿它兜底。
 * 每一项都要输出 detail，侧边栏要把扣分理由原样显示 —— 一个说不清为什么的分数没有用。
 */

import { parseSalary, parseCompanySize } from './job.js';

export const WEIGHTS = {
  direction: 35,
  skills: 30,
  salary: 15,
  companySize: 10,
  publisher: 10
};

/** 出现在职位名里的方向词权重更高：JD 里提一嘴 AI 不代表这是 AI 岗。 */
function scoreDirection(snapshot, profile) {
  const title = String(snapshot.jobTitle || '').toLowerCase();
  const jd = String(snapshot.jobDescription || '').toLowerCase();
  const inTitle = [];
  const inJd = [];
  for (const kw of profile.targetKeywords) {
    const k = kw.toLowerCase();
    if (!k) continue;
    if (title.includes(k)) inTitle.push(kw);
    else if (jd.includes(k)) inJd.push(kw);
  }
  let ratio = 0;
  if (inTitle.length > 0) ratio = Math.min(1, 0.7 + 0.1 * inTitle.length);
  else if (inJd.length >= 3) ratio = 0.55;
  else if (inJd.length > 0) ratio = 0.25 + 0.1 * inJd.length;

  const detail =
    inTitle.length > 0
      ? `职位名命中方向词：${inTitle.join('、')}`
      : inJd.length > 0
        ? `只在 JD 里命中：${inJd.slice(0, 6).join('、')}`
        : '没有命中任何目标方向词';
  return { ratio, detail, matched: [...inTitle, ...inJd] };
}

function scoreSkills(snapshot, profile) {
  const text = `${snapshot.jobTitle || ''}\n${snapshot.jobDescription || ''}\n${(snapshot.tags || []).join(' ')}`.toLowerCase();
  const hit = profile.skills.filter((s) => s && text.includes(s.toLowerCase()));
  // 4 个以上重合就给满分，再多是锦上添花
  const ratio = Math.min(1, hit.length / 4);
  const detail = hit.length ? `技术栈重合 ${hit.length} 项：${hit.join('、')}` : '没有识别到我会的技术栈';
  return { ratio, detail, matched: hit };
}

function scoreSalary(snapshot, profile) {
  const s = parseSalary(snapshot.salaryText);
  if (s.negotiable) return { ratio: 0.5, detail: '薪资面议，按中性算分' };
  if (s.unit !== 'month' || s.max === null) return { ratio: 0.5, detail: '薪资无法解析，按中性算分' };
  if (s.max < profile.salaryMinK) return { ratio: 0, detail: `上限 ${s.max}K 低于底线 ${profile.salaryMinK}K` };
  if (s.min >= profile.salaryIdealK) return { ratio: 1, detail: `下限 ${s.min}K 已达期望 ${profile.salaryIdealK}K` };
  if (s.max >= profile.salaryIdealK) return { ratio: 0.85, detail: `${s.raw}，上限够到期望` };
  return { ratio: 0.65, detail: `${s.raw}，在可接受区间但没到期望` };
}

function scoreCompanySize(snapshot, profile) {
  const raw = String(snapshot.companySizeText || '').trim();
  if (!raw) return { ratio: 0.5, detail: '没拿到公司规模' };
  if (profile.preferredCompanySizes.some((p) => raw.includes(p))) {
    return { ratio: 1, detail: `规模 ${raw}，在偏好档位内` };
  }
  const size = parseCompanySize(raw);
  if (size && size.min >= 1000) return { ratio: 0.2, detail: `规模 ${raw}，属于大厂路线，学历会卡` };
  return { ratio: 0.5, detail: `规模 ${raw}，不在偏好档位` };
}

function scorePublisher(snapshot, profile) {
  const title = String(snapshot.publisherTitle || '');
  if (!title) return { ratio: 0.4, detail: '没拿到发布者身份' };
  const hit = profile.preferredPublisherTitles.find((t) => title.includes(t));
  if (hit) return { ratio: 1, detail: `发布者是「${title}」，命中技术负责人直招` };
  if (/HR|人事|招聘|猎头|助理/i.test(title)) return { ratio: 0.15, detail: `发布者是「${title}」，不是技术线` };
  return { ratio: 0.5, detail: `发布者「${title}」，身份不明确` };
}

/**
 * @returns {{score:number, breakdown:Array, penalties:Array, matchedKeywords:string[]}}
 */
export function scoreJob(snapshot, profile, warnings = []) {
  const parts = [
    { key: 'direction', label: '岗位方向', ...scoreDirection(snapshot, profile) },
    { key: 'skills', label: '技术栈重合', ...scoreSkills(snapshot, profile) },
    { key: 'salary', label: '薪资', ...scoreSalary(snapshot, profile) },
    { key: 'companySize', label: '公司规模', ...scoreCompanySize(snapshot, profile) },
    { key: 'publisher', label: '发布者', ...scorePublisher(snapshot, profile) }
  ];

  let total = 0;
  const breakdown = parts.map((p) => {
    const weight = WEIGHTS[p.key];
    const points = Math.round(p.ratio * weight);
    total += points;
    return { key: p.key, label: p.label, points, weight, detail: p.detail };
  });

  // 硬筛留下的警告，每条扣 5 分，最多扣 15
  const penalties = warnings.slice(0, 3).map((w) => ({ reason: w, points: -5 }));
  total += penalties.reduce((sum, p) => sum + p.points, 0);

  const matchedKeywords = [
    ...(parts[0].matched || []),
    ...(parts[1].matched || [])
  ];

  return {
    score: Math.max(0, Math.min(100, total)),
    breakdown,
    penalties,
    matchedKeywords: [...new Set(matchedKeywords)]
  };
}
