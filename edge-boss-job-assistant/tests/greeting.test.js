import test from 'node:test';
import assert from 'node:assert/strict';
import { validateGreeting, validateGreetingPayload, charCount, factAnchors } from '../src/domain/greeting.js';
import { normalizeProfile } from '../src/domain/profile.js';

const profile = normalizeProfile({});

/** 一条合格的招呼语：有 JD 匹配点、有真实项目、没数字、没套话。 */
const GOOD =
  '您好，看到岗位要求做 Agent 工具编排和 RAG 检索优化。我做过一个智能出行 Agent，用原生 Function Calling 编排多轮规划，' +
  '没套框架；另一个教师招聘项目用 RAG 做公告问答，回答带可点击出处。两个都在 GitHub 上，带 Docker 和测试，方便的话我发您链接。';

test('合格的招呼语能过', () => {
  const r = validateGreeting(GOOD, profile);
  assert.equal(r.ok, true, r.errors.join('；'));
  assert.ok(r.anchorsHit.length > 0);
});

test('字数统计按字符算，中文不按字节', () => {
  assert.equal(charCount('你好abc'), 5);
  assert.equal(charCount('  你好  '), 2);
});

test('太短的直接否', () => {
  const r = validateGreeting('您好，我很感兴趣，做过 RAG 项目。', profile);
  assert.equal(r.ok, false);
  assert.ok(r.errors.some((e) => e.includes('太短')));
});

test('太长的直接否', () => {
  const r = validateGreeting(GOOD.repeat(3), profile);
  assert.equal(r.ok, false);
  assert.ok(r.errors.some((e) => e.includes('超过上限')));
});

test('套话一律拦掉', () => {
  for (const filler of ['贵司前景广阔', '深受启发', '一直很关注贵公司', '恳请给个机会']) {
    const text = GOOD.slice(0, 70) + filler + GOOD.slice(70, 110);
    const r = validateGreeting(text, profile);
    assert.equal(r.ok, false, `「${filler}」没被拦住`);
    assert.ok(r.errors.some((e) => e.includes('套话')));
  }
});

test('编造的量化指标一律拦掉 —— 这是最要命的一类', () => {
  const cases = [
    '准确率提升了 35%',
    '处理了 160 条工单',
    '支撑 500 QPS',
    '服务过 10 万用户',
    '召回率达到 95'
  ];
  for (const c of cases) {
    const text = GOOD.slice(0, 60) + c + GOOD.slice(60, 100);
    const r = validateGreeting(text, profile);
    assert.equal(r.ok, false, `「${c}」没被拦住`);
    assert.ok(
      r.errors.some((e) => e.includes('量化')),
      `「${c}」拦住了但理由不对：${r.errors.join('；')}`
    );
  }
});

test('模板占位符没替换掉的拦掉', () => {
  for (const ph of ['【公司名】', '{{position}}', 'XX科技', '某某公司']) {
    const text = GOOD.slice(0, 60) + ph + GOOD.slice(60, 100);
    const r = validateGreeting(text, profile);
    assert.equal(r.ok, false, `「${ph}」没被拦住`);
  }
});

test('没引用任何真实项目的空泛招呼语拦掉', () => {
  const empty =
    '您好，我是今年毕业的计算机专业学生，对这个岗位很感兴趣，学习能力强，希望能有机会和您聊聊，我可以随时到岗，谢谢您抽时间看我的消息，期待回复。';
  const r = validateGreeting(empty, profile);
  assert.equal(r.ok, false);
  assert.ok(r.errors.some((e) => e.includes('事实库')));
});

test('字数在硬限内但不在理想区间 → 只警告不拦', () => {
  const text = '您好，岗位提到 RAG 和 Agent 方向。我做过智能出行 Agent，用 Function Calling 编排多轮规划，代码在 GitHub 上。';
  const r = validateGreeting(text, profile);
  assert.ok(charCount(text) >= 60 && charCount(text) < 80, `fixture 字数应落在 60–80，实际 ${charCount(text)}`);
  assert.equal(r.ok, true, r.errors.join('；'));
  assert.ok(r.warnings.some((w) => w.includes('理想区间')));
});

test('空招呼语', () => {
  assert.equal(validateGreeting('', profile).ok, false);
  assert.equal(validateGreeting(null, profile).ok, false);
});

test('事实库锚点里包含项目名和技术名词', () => {
  const anchors = factAnchors(profile.facts);
  assert.ok(anchors.includes('智能出行 Agent 助手'));
  assert.ok(anchors.some((a) => a.includes('RAG') || a.includes('Function Calling')));
});

test('模型返回体：正常', () => {
  const r = validateGreetingPayload(
    { greeting: GOOD, jd_point_used: 'Agent 工具编排', fact_used: '智能出行 Agent', char_count: 120 },
    profile
  );
  assert.equal(r.ok, true, (r.errors || []).join('；'));
  assert.equal(r.value.jd_point_used, 'Agent 工具编排');
});

test('模型返回体：正文不合格就整个否掉，不做修补', () => {
  const r = validateGreetingPayload({ greeting: '贵司前景广阔，我很想加入', jd_point_used: 'x' }, profile);
  assert.equal(r.ok, false);
  assert.equal(r.value, null);
});

test('模型返回体：不是对象', () => {
  assert.equal(validateGreetingPayload(null, profile).ok, false);
  assert.equal(validateGreetingPayload('一段话', profile).ok, false);
});
