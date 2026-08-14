/**
 * 决策流水线：硬筛 → 规则分 → 模型匹配 → 公开信息背调 → 决策。
 *
 * 每一步都可以单独失败。失败就把原因写进 degraded，继续往下走，
 * 最后由 decide() 决定降级到什么程度 —— 但绝不会因为「没查到坏消息」就给绿灯。
 */

import { runHardFilter } from '../domain/hard-filter.js';
import { scoreJob } from '../domain/score.js';
import { decide, collectSources, DECISION } from '../domain/decision.js';
import { jobKey, isUsableSnapshot } from '../domain/job.js';
import { validateMatch, validateVerification, parseJsonStrict } from '../domain/schema.js';
import { MATCH_SYSTEM, buildMatchPrompt } from '../prompts/match.js';
import { VERIFY_SYSTEM, buildVerifyPrompt, buildSearchQueries } from '../prompts/verify.js';
import { chatJson } from './llm-client.js';
import { searchMany } from './search-client.js';
import * as store from '../storage/store.js';

/**
 * @param {object} snapshot 岗位快照（只读）
 * @param {object} profile
 * @param {object} apiConfig
 * @returns {Promise<object>} 评估结果
 */
export async function evaluate(snapshot, profile, apiConfig) {
  const key = jobKey(snapshot);
  const degraded = [];

  if (!isUsableSnapshot(snapshot)) {
    return {
      ok: false,
      jobKey: key,
      error: 'unreadable',
      message: '页面没抓到职位名/公司名，无法判断',
      missingFields: snapshot.missingFields || []
    };
  }

  // 1. 硬筛
  const hardFilter = runHardFilter(snapshot, profile);

  // 2. 规则分
  const ruleScore = scoreJob(snapshot, profile, hardFilter.warnings);

  // 硬筛没过就不必再花钱了
  if (!hardFilter.passed) {
    const result = decide({ hardFilter, ruleScore, llmMatch: null, verification: null, profile, degraded });
    return finish({ key, snapshot, hardFilter, ruleScore, llmMatch: null, verification: null, result, sources: [] });
  }

  // 3. 模型匹配
  let llmMatch = null;
  if (apiConfig.enableLlm && apiConfig.llmApiKey) {
    if (!(await store.canCallLlm(apiConfig))) {
      degraded.push(`今日模型调用已达上限 ${apiConfig.dailyLlmLimit} 次`);
    } else {
      try {
        const text = await chatJson({
          baseUrl: apiConfig.llmBaseUrl,
          apiKey: apiConfig.llmApiKey,
          model: apiConfig.llmModel,
          system: MATCH_SYSTEM,
          user: buildMatchPrompt(snapshot, profile)
        });
        await store.bumpUsage('llmCalls');
        const parsed = parseJsonStrict(text);
        if (!parsed.ok) {
          degraded.push(`模型输出不是合法 JSON：${parsed.error}`);
        } else {
          const validated = validateMatch(parsed.value);
          if (!validated.ok) degraded.push(`模型输出结构不合法：${validated.errors.join('；')}`);
          else llmMatch = validated.value;
        }
      } catch (e) {
        degraded.push(`模型匹配失败：${e.message}`);
      }
    }
  } else {
    degraded.push('未启用模型匹配');
  }

  // 4. 公开信息背调
  let verification = null;
  let searchResults = [];
  if (apiConfig.enableSearch && apiConfig.searchApiKey && apiConfig.searchProvider !== 'none') {
    try {
      const queries = buildSearchQueries(snapshot, profile);
      const { results, errors } = await searchMany({
        provider: apiConfig.searchProvider,
        apiKey: apiConfig.searchApiKey,
        queries
      });
      searchResults = results;
      await store.bumpUsage('searchCalls', queries.length);
      if (errors.length) degraded.push(`部分检索失败：${errors[0]}`);

      if (results.length === 0) {
        degraded.push('检索没有返回任何结果');
      } else if (!apiConfig.llmApiKey || !apiConfig.enableLlm) {
        degraded.push('有检索结果但没启用模型，无法归纳背调结论');
      } else if (!(await store.canCallLlm(apiConfig))) {
        degraded.push('模型调用已达上限，跳过背调归纳');
      } else {
        const text = await chatJson({
          baseUrl: apiConfig.llmBaseUrl,
          apiKey: apiConfig.llmApiKey,
          model: apiConfig.llmModel,
          system: VERIFY_SYSTEM,
          user: buildVerifyPrompt(snapshot, results)
        });
        await store.bumpUsage('llmCalls');
        const parsed = parseJsonStrict(text);
        if (!parsed.ok) {
          degraded.push(`背调输出不是合法 JSON：${parsed.error}`);
        } else {
          const validated = validateVerification(parsed.value, results.map((r) => r.url));
          if (!validated.ok) degraded.push(`背调输出结构不合法：${validated.errors.join('；')}`);
          else verification = validated.value;
        }
      }
    } catch (e) {
      degraded.push(`背调失败：${e.message}`);
    }
  } else {
    degraded.push('未启用公开信息背调');
  }

  // 5. 决策
  const result = decide({ hardFilter, ruleScore, llmMatch, verification, profile, degraded });
  return finish({
    key,
    snapshot,
    hardFilter,
    ruleScore,
    llmMatch,
    verification,
    result,
    sources: collectSources(verification),
    searchResults
  });
}

function finish({ key, snapshot, hardFilter, ruleScore, llmMatch, verification, result, sources, searchResults = [] }) {
  return {
    ok: true,
    jobKey: key,
    evaluatedAt: Date.now(),
    snapshot,
    hardFilter,
    ruleScore,
    llmMatch,
    verification,
    sources,
    searchResults,
    decision: result.decision,
    finalScore: result.finalScore,
    headline: result.headline,
    reasons: result.reasons,
    notes: result.notes,
    conflicts: result.conflicts
  };
}

export { DECISION };
