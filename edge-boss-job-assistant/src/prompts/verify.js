/**
 * 公司真实性背调提示词（设计文档 §4.1 第三层）。
 *
 * 这一层最容易出幻觉：模型很乐意替一家它没听说过的公司编一段「主营 AI 解决方案」。
 * 所以提示词里只给检索到的片段，并要求每条结论都挂 url + 原文摘录，
 * 校验层再把不在检索结果里的 URL 全部丢掉。
 */

export const VERIFY_SYSTEM = `你是一个尽职调查分析员。你只输出 JSON，不输出任何解释性文字。

铁律：
1. 你只能使用「检索结果」里出现的内容。你自己的先验知识、对公司的印象、对行业的推测，一律不算证据。
2. 每一条结论都必须附带 sources，每个 source 必须包含检索结果里真实存在的 url 和一段原文摘录 quote。
3. 找不到足够材料时，conclusion 直接写「信息不足」，sources 给空数组。不许用「可能」「据推测」来填。
4. 只有当不同来源之间真的互相打架时，才写进 consistency_conflicts。没有矛盾就给空数组。
5. severity 判定：
   - high：JD 声称做 AI 研发但公开信息显示主业是培训/招生/销售/劳务；技术岗实为外包驻场；发布者身份与「技术负责人直招」明显冲突；工商状态异常（注销、吊销、大量被执行）。
   - medium：来源之间口径不一致，但不足以定性。
   - low：细节出入。`;

export function buildVerifyPrompt(snapshot, searchResults) {
  const blocks = searchResults
    .map((r, i) => `### 来源 ${i + 1}\nURL: ${r.url}\n标题: ${r.title || ''}\n内容: ${String(r.content || '').slice(0, 1200)}`)
    .join('\n\n');

  return `## 待核验岗位

公司名：${snapshot.companyName}
职位：${snapshot.jobTitle}
公司行业（BOSS 页面自称）：${snapshot.companyIndustry || '未知'}
公司规模（BOSS 页面自称）：${snapshot.companySizeText || '未知'}
发布者（BOSS 页面自称）：${snapshot.publisherTitle || '未知'}
JD 摘要：${String(snapshot.jobDescription || '').slice(0, 1200)}

## 检索结果

${blocks || '（没有检索到任何结果）'}

## 任务

基于且仅基于上面的检索结果，核验四件事，用 JSON 回答：

1. business_match：公司实际业务/官网产品/公开动态，是否支撑 JD 里的 AI/技术业务描述
2. publisher_check：发布者身份、同公司其他岗位、公司技术痕迹，是否支撑「技术负责人直招」
3. going_concern：公司是否有持续经营和真实产品/客户的迹象
4. consistency_conflicts：工作制、岗位职责、薪资、外包属性等在不同来源之间是否矛盾

输出格式：

{
  "verdict": "supported | insufficient | contradicted",
  "business_match": { "conclusion": "...", "sources": [{ "url": "...", "quote": "..." }] },
  "publisher_check": { "conclusion": "...", "sources": [] },
  "going_concern": { "conclusion": "...", "sources": [] },
  "consistency_conflicts": [
    { "severity": "high|medium|low", "description": "...", "sources": [{ "url": "...", "quote": "..." }] }
  ],
  "summary": "一句话结论，40 字以内"
}`;
}

/** 检索词：公司名 + 城市 + JD 关键词，外加两个专门用来抓雷的查询。 */
export function buildSearchQueries(snapshot, profile) {
  const company = snapshot.companyName;
  if (!company) return [];
  return [
    `${company} ${profile.city} 公司 主营业务`,
    `${company} 招聘 ${snapshot.jobTitle} 怎么样`,
    `${company} 外包 培训 投诉 口碑`
  ];
}
