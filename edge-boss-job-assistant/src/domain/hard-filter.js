/**
 * 第一层：硬筛选（设计文档 §4.1）。
 * 只做「一票否决」，不打分。命中就 skip，理由必须能一句话说清楚。
 */

import { parseSalary, parseExperience, parseEducationRank, MY_EDU_RANK } from './job.js';

/**
 * JD 正文里出现这些说法，基本可以断定是外包/驻场/培训招生，直接否。
 * 单独一个「销售」出现在 JD 里不算 —— 给销售团队做系统的技术岗是正常的，
 * 所以普通屏蔽词只在职位名上做硬否决，JD 里只当作扣分信号。
 */
const STRONG_JD_PATTERNS = [
  /人力(资源)?外包/,
  /外包(项目|公司|岗|驻场)/,
  /驻场(开发|办公|支持|服务)/,
  /派驻(甲方|客户)/,
  /劳务派遣/,
  /(招生|生源)(任务|指标|老师|顾问)/,
  /(课程|学员)(顾问|销售)/,
  /培训(机构|学员).{0,8}(招生|销售|转化)/,
  /(电话|电销).{0,6}(邀约|开发客户)/,
  /(业绩|销售)(指标|提成).{0,10}(考核|挂钩)/
];

/**
 * @returns {{passed:boolean, reasons:string[], warnings:string[]}}
 */
export function runHardFilter(snapshot, profile) {
  const reasons = [];
  const warnings = [];
  const title = String(snapshot.jobTitle || '');
  const jd = String(snapshot.jobDescription || '');
  const haystackTitle = title.toLowerCase();

  // 1. 职位名命中屏蔽词
  for (const word of profile.blocklist) {
    if (!word) continue;
    if (haystackTitle.includes(word.toLowerCase())) {
      reasons.push(`职位名含屏蔽词「${word}」`);
    }
  }

  // 2. JD 强特征
  for (const re of STRONG_JD_PATTERNS) {
    const m = jd.match(re);
    if (m) reasons.push(`JD 命中外包/培训特征「${m[0]}」`);
  }

  // 3. JD 里出现普通屏蔽词只警告
  for (const word of profile.blocklist) {
    if (!word) continue;
    if (!haystackTitle.includes(word.toLowerCase()) && jd.includes(word)) {
      warnings.push(`JD 出现「${word}」，需人工看上下文`);
    }
  }

  // 4. 城市
  if (profile.city) {
    const cityText = `${snapshot.cityText || ''}${snapshot.districtText || ''}`;
    if (cityText && !cityText.includes(profile.city)) {
      reasons.push(`工作城市「${cityText}」不是${profile.city}`);
    }
  }

  // 5. 薪资
  const salary = parseSalary(snapshot.salaryText);
  if (salary.unit === 'day' || salary.unit === 'hour') {
    reasons.push(`按${salary.unit === 'day' ? '天' : '小时'}结算（${salary.raw}），基本是临时/外包`);
  } else if (profile.rejectBelowMinSalary && salary.unit === 'month' && salary.max !== null) {
    if (salary.max < profile.salaryMinK) {
      reasons.push(`薪资上限 ${salary.max}K 低于底线 ${profile.salaryMinK}K`);
    }
  } else if (salary.negotiable) {
    warnings.push('薪资面议，无法预筛');
  }

  // 6. 学历
  const eduRank = parseEducationRank(snapshot.educationText);
  const myRank = MY_EDU_RANK[profile.educationLevel] ?? MY_EDU_RANK.bachelor;
  if (eduRank !== null && eduRank > myRank) {
    reasons.push(`学历要求「${snapshot.educationText}」高于本科`);
  }

  // 7. 经验
  const exp = parseExperience(snapshot.experienceText);
  if (exp.minYears !== null && exp.minYears > profile.maxRequiredYears) {
    reasons.push(`要求 ${exp.minYears} 年经验，超过上限 ${profile.maxRequiredYears} 年`);
  }

  return { passed: reasons.length === 0, reasons, warnings };
}
