/**
 * 第三层：合并成最终决策（设计文档 §4.2）。
 *
 * 只读版的语义：
 *   apply  = 绿灯，建议投，但发送键由你自己按
 *   review = 黄灯，有疑点，值得看一眼再决定
 *   skip   = 红灯，别浪费打招呼次数
 *
 * 降级原则（设计文档 §9）：模型或检索挂了，就只用规则分，
 * 并且封顶到 review —— 缺证据时不允许给绿灯。
 */

export const DECISION = { APPLY: 'apply', REVIEW: 'review', SKIP: 'skip' };

/** LLM 匹配分占比更高：它读得懂 JD，规则只会数关键词。 */
const RULE_WEIGHT = 0.4;
const LLM_WEIGHT = 0.6;

/**
 * @param {object} input
 * @param {{passed:boolean,reasons:string[],warnings:string[]}} input.hardFilter
 * @param {{score:number,breakdown:Array,penalties:Array}} input.ruleScore
 * @param {{match_score:number,summary:string}|null} input.llmMatch
 * @param {{verdict:string,consistency_conflicts:Array,sources:Array}|null} input.verification
 * @param {{enabled:boolean,evaluated:boolean,score:number,minScore:number,filtered:boolean}|null} input.preference
 * @param {object} input.profile
 * @param {string[]} input.degraded 降级说明，例如「模型调用失败」
 */
export function decide({ hardFilter, ruleScore, llmMatch, verification, preference = null, profile, degraded = [] }) {
  const notes = [...degraded];

  if (!hardFilter.passed) {
    return {
      decision: DECISION.SKIP,
      finalScore: 0,
      headline: hardFilter.reasons[0] || '硬筛未通过',
      reasons: hardFilter.reasons,
      notes,
      conflicts: []
    };
  }

  const hasLlm = llmMatch && Number.isFinite(Number(llmMatch.match_score));
  const finalScore = hasLlm
    ? Math.round(RULE_WEIGHT * ruleScore.score + LLM_WEIGHT * Number(llmMatch.match_score))
    : ruleScore.score;
  if (!hasLlm) notes.push('没有模型匹配结果，用纯规则分');

  const conflicts = (verification?.consistency_conflicts || []).filter(Boolean);
  const highRisk = conflicts.filter((c) => c.severity === 'high');
  const mediumRisk = conflicts.filter((c) => c.severity === 'medium');
  const sources = collectSources(verification);
  const hasVerifiableSource = sources.length > 0;

  const reasons = [];
  if (hasLlm && llmMatch.summary) reasons.push(llmMatch.summary);
  if (verification?.summary) reasons.push(verification.summary);

  // 高风险矛盾一票否决，分数再高也不投
  if (highRisk.length > 0) {
    return {
      decision: DECISION.SKIP,
      finalScore,
      headline: `发现高风险矛盾：${highRisk[0].description}`,
      reasons,
      notes,
      conflicts
    };
  }

  // 偏好过滤：你自己写的「不愿意去」的条件，优先级高于分数
  if (preference?.enabled && preference.evaluated && preference.filtered) {
    const worst = [...(preference.negative || [])].sort((a, b) => b.score - a.score)[0];
    return {
      decision: DECISION.SKIP,
      finalScore,
      headline: `偏好过滤：净分 ${preference.score} 低于 ${preference.minScore}${worst ? `（${worst.item}）` : ''}`,
      reasons: [...reasons, ...(preference.negative || []).map((n) => `扣分 ${n.score}：${n.reason}`)],
      notes,
      conflicts
    };
  }
  if (preference?.enabled && !preference.evaluated) notes.push('偏好过滤没跑（模型没结果），本次不参与决策');

  if (finalScore < profile.reviewThreshold) {
    return {
      decision: DECISION.SKIP,
      finalScore,
      headline: `匹配分 ${finalScore}，低于 ${profile.reviewThreshold}`,
      reasons,
      notes,
      conflicts
    };
  }

  if (finalScore >= profile.applyThreshold && !hasLlm) {
    notes.push('规则分够绿灯，但缺模型判断，压到黄灯');
    return {
      decision: DECISION.REVIEW,
      finalScore,
      headline: `规则分 ${finalScore}，但没有模型和背调结果`,
      reasons,
      notes,
      conflicts
    };
  }

  if (finalScore >= profile.applyThreshold && mediumRisk.length === 0 && hasVerifiableSource) {
    return {
      decision: DECISION.APPLY,
      finalScore,
      headline: `匹配分 ${finalScore}，背调无矛盾，建议投`,
      reasons,
      notes,
      conflicts
    };
  }

  const why = [];
  if (finalScore < profile.applyThreshold) why.push(`匹配分 ${finalScore}`);
  if (mediumRisk.length > 0) why.push(`中风险矛盾：${mediumRisk[0].description}`);
  if (!hasVerifiableSource) why.push('背调没有拿到可核验来源');

  return {
    decision: DECISION.REVIEW,
    finalScore,
    headline: why.join('；') || '需要人工确认',
    reasons,
    notes,
    conflicts
  };
}

/** 把背调结果里所有带 URL 的来源摊平，用于「至少一条可核验来源」的判断和展示。 */
export function collectSources(verification) {
  if (!verification) return [];
  const buckets = [
    verification.business_match,
    verification.publisher_check,
    verification.going_concern
  ];
  const out = [];
  for (const b of buckets) {
    for (const s of b?.sources || []) {
      if (s && s.url) out.push(s);
    }
  }
  for (const c of verification.consistency_conflicts || []) {
    for (const s of c?.sources || []) {
      if (s && s.url) out.push(s);
    }
  }
  const seen = new Set();
  return out.filter((s) => {
    if (seen.has(s.url)) return false;
    seen.add(s.url);
    return true;
  });
}

export function decisionLabel(decision) {
  return { apply: '建议投', review: '待定', skip: '别投' }[decision] || '未知';
}

export function decisionColor(decision) {
  return { apply: '#1a7f37', review: '#9a6700', skip: '#b42318' }[decision] || '#57606a';
}
