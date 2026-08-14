/**
 * 岗位匹配提示词（设计文档 §4.1 第二层）。
 *
 * 两条硬约束：
 * 1. 证据只能来自事实库，JD 里的要求不等于我会；
 * 2. 输出必须是 JSON —— DeepSeek 开 json_object 模式时，提示词里必须出现 "JSON" 字样，
 *    否则接口直接报错，这是踩过的坑。
 */

import { factsToPromptText } from '../domain/profile.js';

export const MATCH_SYSTEM = `你是一个严格的求职匹配评估器。你只输出 JSON，不输出任何解释性文字。

铁律：
1. 候选人的能力证据只能来自「候选人事实库」。事实库里没有的技术、经历、数字，一律视为候选人不具备。
2. 绝对不许把 JD 的要求改写成候选人的经历。JD 说「需要 3 年 Java」不代表候选人有 Java 经验。
3. 事实库里标注为「不许引用」或「还没有评测证据」的内容，不能写进 matched_points。
4. 打分要吝啬。JD 的核心要求如果在事实库里找不到对应证据，就是 gap，必须扣分。
5. 察觉到 JD 名不副实（挂技术岗名义实际做销售、招生、客服、驻场），写进 doubts。`;

export function buildMatchPrompt(snapshot, profile) {
  const facts = factsToPromptText(profile.facts);
  return `## 岗位信息

职位：${snapshot.jobTitle}
公司：${snapshot.companyName}
薪资：${snapshot.salaryText || '未知'}
地点：${snapshot.cityText || ''}${snapshot.districtText || ''}
经验要求：${snapshot.experienceText || '未知'}
学历要求：${snapshot.educationText || '未知'}
公司规模：${snapshot.companySizeText || '未知'}
公司行业：${snapshot.companyIndustry || '未知'}
发布者：${snapshot.publisherTitle || '未知'}

### JD 原文
${(snapshot.jobDescription || '（页面没有抓到 JD 正文）').slice(0, 4000)}

## 候选人事实库

身份：2026 届计算机本科应届生，目标城市${profile.city}，期望 ${profile.salaryMinK}-${profile.salaryIdealK}K。

${facts}

## 任务

评估这个岗位和候选人的匹配度，只用 JSON 回答，格式如下：

{
  "match_score": 0 到 100 的整数,
  "matched_points": [
    { "jd_requirement": "JD 里的具体要求原文", "my_evidence": "事实库里对应的证据原文", "evidence_source": "项目名或实习" }
  ],
  "gaps": ["JD 要求但事实库里没有证据的点"],
  "doubts": ["对这个岗位真实性或内容的疑点，没有就给空数组"],
  "summary": "一句话结论，30 字以内"
}`;
}

export const MATCH_SCHEMA_HINT = 'match_score / matched_points / gaps / doubts / summary';
