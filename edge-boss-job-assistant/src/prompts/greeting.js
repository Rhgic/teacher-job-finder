/**
 * 招呼语生成（设计文档 §5.1）。
 *
 * BOSS 的技术负责人一天翻几十条招呼，泛泛的「贵司前景好」两秒就被划走。
 * 一条有用的招呼语只干三件事：说清我看懂了你这个岗位在招什么、
 * 甩一个能点开验证的项目、给一个明确的下一步。
 *
 * 唯一的红线是不许编。事实库里没有的经历和数字，一个字都不许出现。
 */

import { factsToPromptText } from '../domain/profile.js';

export const GREETING_SYSTEM = `你在帮一个 2026 届应届生写 BOSS 直聘的打招呼语。你只输出 JSON。

铁律：
1. 只能使用「候选人事实库」里的内容。事实库里没有的公司、经历、数字、指标，一个字都不许写。
2. 不许写任何未经证实的量化结果（准确率、条数、提升百分比、用户量）。事实库里没有这些数字，你也不许造。
3. 不许写「贵司前景广阔」「深受启发」「一直关注贵司」这类空话，招聘的人一天看几十条，这种话直接被划走。
4. 必须具体提到这个 JD 里的一个真实要求，证明是看过 JD 才发的，不是群发。
5. 必须带一个候选人真实做过的项目，并且说清这个项目和那条 JD 要求是怎么对上的。
6. 语气是同行之间说话，不是求人。不卑不亢，不用敬语堆砌，不说"恳请""万分"。
7. 全文 80 到 140 个字，一段话，不分行，不用 emoji，不留任何占位符。`;

export function buildGreetingPrompt(snapshot, profile, llmMatch) {
  const facts = factsToPromptText(profile.facts);
  const matched = (llmMatch?.matched_points || [])
    .map((m) => `- JD 要求「${m.jd_requirement}」 ↔ 我的证据「${m.my_evidence}」（${m.evidence_source}）`)
    .join('\n');

  return `## 岗位

职位：${snapshot.jobTitle}
公司：${snapshot.companyName}
发布者：${snapshot.publisherTitle || '未知'}

### JD 原文
${String(snapshot.jobDescription || '').slice(0, 2000)}

## 已经分析出的匹配点

${matched || '（没有现成的匹配点，请自己从 JD 和事实库里找）'}

## 候选人事实库

${facts}

## 任务

写一条打招呼语，用 JSON 回答：

{
  "greeting": "80-140 字的招呼语正文",
  "jd_point_used": "用到的那条 JD 要求原文",
  "fact_used": "用到的那条项目事实，必须能在事实库里找到",
  "char_count": 字数（整数）
}`;
}
