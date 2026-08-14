import test from 'node:test';
import assert from 'node:assert/strict';
import { validateMatch, validateVerification, parseJsonStrict } from '../src/domain/schema.js';

test('parseJsonStrict 能剥掉代码围栏', () => {
  const r = parseJsonStrict('```json\n{"a":1}\n```');
  assert.equal(r.ok, true);
  assert.equal(r.value.a, 1);
});

test('parseJsonStrict 对垃圾输入直接失败，不做修补', () => {
  const r = parseJsonStrict('这是我的分析：分数 80 分');
  assert.equal(r.ok, false);
  assert.equal(r.value, null);
});

test('匹配结果：合法输入通过', () => {
  const r = validateMatch({
    match_score: 82,
    matched_points: [{ jd_requirement: '熟悉 RAG', my_evidence: '教师招聘项目做过 RAG', evidence_source: '项目' }],
    gaps: ['没做过分布式训练'],
    doubts: [],
    summary: '方向对口'
  });
  assert.equal(r.ok, true);
  assert.equal(r.value.match_score, 82);
  assert.equal(r.value.matched_points.length, 1);
});

test('匹配结果：分数越界 → 失败', () => {
  assert.equal(validateMatch({ match_score: 120, summary: 'x' }).ok, false);
  assert.equal(validateMatch({ match_score: 'high', summary: 'x' }).ok, false);
});

test('匹配结果：缺 summary → 失败', () => {
  assert.equal(validateMatch({ match_score: 80 }).ok, false);
});

test('匹配结果：残缺的 matched_point 被丢掉，不算整体失败', () => {
  const r = validateMatch({
    match_score: 70,
    matched_points: [{ jd_requirement: '会 Python' }, { jd_requirement: '会 RAG', my_evidence: '做过' }],
    summary: 'ok'
  });
  assert.equal(r.ok, true);
  assert.equal(r.value.matched_points.length, 1);
});

test('背调：模型编的 URL 会被剔除', () => {
  const allowed = ['https://real.com/about'];
  const r = validateVerification(
    {
      verdict: 'supported',
      business_match: {
        conclusion: '主营 AI',
        sources: [
          { url: 'https://real.com/about', quote: '我们做 AI' },
          { url: 'https://hallucinated.com/x', quote: '编的' }
        ]
      },
      summary: 'ok'
    },
    allowed
  );
  assert.equal(r.ok, true);
  assert.equal(r.value.business_match.sources.length, 1);
  assert.equal(r.value.business_match.sources[0].url, 'https://real.com/about');
});

test('背调：有结论但一条来源都没有 → 降级为信息不足', () => {
  const r = validateVerification(
    { verdict: 'supported', business_match: { conclusion: '这家公司很不错', sources: [] }, summary: 'ok' },
    ['https://real.com/about']
  );
  assert.ok(r.value.business_match.conclusion.includes('信息不足'));
  assert.equal(r.value.business_match.grounded, false);
  assert.equal(r.value.verdict, 'insufficient');
});

test('背调：没来源撑着的高风险指控降为中风险，避免幻觉毙掉好岗位', () => {
  const r = validateVerification(
    {
      verdict: 'contradicted',
      consistency_conflicts: [{ severity: 'high', description: '疑似皮包公司', sources: [] }],
      summary: 'x'
    },
    ['https://real.com/a']
  );
  assert.equal(r.value.consistency_conflicts[0].severity, 'medium');
  assert.ok(r.value.consistency_conflicts[0].description.includes('已降级'));
});

test('背调：有来源的高风险保留，并把总结论拉成 contradicted', () => {
  const r = validateVerification(
    {
      verdict: 'supported',
      business_match: { conclusion: '主营 AI', sources: [{ url: 'https://real.com/a', quote: 'AI' }] },
      consistency_conflicts: [
        { severity: 'high', description: '公开信息显示主业是招生', sources: [{ url: 'https://real.com/a', quote: '招生' }] }
      ],
      summary: 'x'
    },
    ['https://real.com/a']
  );
  assert.equal(r.value.consistency_conflicts[0].severity, 'high');
  assert.equal(r.value.verdict, 'contradicted');
});

test('背调：非法 verdict 一律当信息不足', () => {
  const r = validateVerification({ verdict: '还行吧', summary: 'x' }, []);
  assert.equal(r.value.verdict, 'insufficient');
});

test('背调：不给 allowlist 时只校验 URL 格式', () => {
  const r = validateVerification(
    { verdict: 'supported', business_match: { conclusion: 'x', sources: [{ url: 'not-a-url', quote: 'q' }] }, summary: 's' },
    []
  );
  assert.equal(r.value.business_match.sources.length, 0);
});

test('两个校验器都不接受 null', () => {
  assert.equal(validateMatch(null).ok, false);
  assert.equal(validateVerification(null).ok, false);
});
