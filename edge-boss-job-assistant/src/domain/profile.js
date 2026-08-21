/**
 * 求职画像与「简历事实库」。
 *
 * 事实库遵守仓库根目录《求职事实核验表》的原则：
 * 只放能从代码、测试输出、Git 历史或部署记录里证明的东西。
 * 没跑过的指标（QPS、召回率、自动解决率、工单条数）一律不进这里，
 * 因为下游会把这些条目当成「可验证事实」直接用于判断和展示。
 */

import { DEFAULT_PREFERENCE, normalizePreference } from './preference.js';

/** 硬性排除关键词：命中即 skip，不进入打分。 */
export const DEFAULT_BLOCKLIST = [
  '外包',
  '外派',
  '驻场',
  '劳务派遣',
  '人力资源服务',
  'BPO',
  '培训',
  '招生',
  '学员',
  '讲师',
  '销售',
  '电销',
  '地推',
  '客户经理',
  '业务经理',
  '渠道经理',
  '中介',
  '猎头',
  '保险',
  '房产经纪'
];

/** 加分关键词：出现在职位名或 JD 里说明方向对。 */
export const DEFAULT_TARGET_KEYWORDS = [
  'AI 应用',
  'AI应用',
  'Agent',
  '智能体',
  '大模型',
  'LLM',
  'AIGC',
  'RAG',
  '知识库问答',
  'Python',
  'prompt',
  '提示词',
  'Function Calling',
  'MCP',
  'LangChain',
  'LangGraph',
  '算法工程',
  'AI 产品'
];

/** 我能拿出证据的技术栈。命中越多，规则分越高。 */
export const DEFAULT_SKILLS = [
  'Python',
  'FastAPI',
  'Pydantic',
  'SQLAlchemy',
  'RAG',
  '向量检索',
  'Function Calling',
  'MCP',
  'Agent',
  'LangChain',
  'LangGraph',
  'DeepSeek',
  'Docker',
  'MySQL',
  'Redis',
  'PostgreSQL',
  'pgvector',
  '微信小程序'
];

/**
 * 项目事实库。每条 claim 必须有 evidence（在哪能看到）。
 * 只有这里的条目允许被引用为「可验证的项目事实」。
 */
export const DEFAULT_FACTS = [
  {
    id: 'travel-agent',
    project: '智能出行 Agent 助手',
    url: 'https://github.com/Rhgic/smart-travel-agent',
    claims: [
      { text: '用原生 Function Calling 编排多轮出行规划，不依赖 Agent 框架', evidence: '仓库源码' },
      { text: '接入 MCP 协议与高德地图 API，维护多轮 Trip State', evidence: '仓库源码' },
      { text: '带 Docker 部署与 pytest 测试', evidence: '仓库 Dockerfile 与 tests/' }
    ]
  },
  {
    id: 'teacher-job-finder',
    project: '教师招聘 AI 匹配与 RAG 问答',
    url: 'https://github.com/Rhgic/teacher-job-finder',
    claims: [
      { text: '规则 + LLM 两阶段匹配，先规则过滤再让模型解释匹配理由', evidence: '仓库源码' },
      { text: '公告问答用 RAG，回答带可点击出处', evidence: '仓库源码' },
      { text: 'FastAPI + MySQL 后端，Alembic 迁移，GitHub Actions 三任务 CI', evidence: '仓库 .github/workflows 与 alembic/' },
      { text: 'Redis 做 LLM 配额、限流与结果缓存', evidence: '仓库源码' },
      { text: '爬虫做正文级复检，拦截成绩公示与广告等非招聘内容', evidence: '仓库源码与提交历史' }
    ]
  },
  {
    id: 'cbec-support-agent',
    project: '跨境电商客服 Agent',
    url: '',
    claims: [
      { text: 'PostgreSQL + pgvector 单库方案，检索与业务数据不分家', evidence: '仓库源码' }
    ],
    note: '在建项目。任何效果类指标（工单条数、自动解决率、高风险拦截率）都还没有评测证据，不许引用。'
  },
  {
    id: 'internship',
    project: '码全科技 · Agent 应用开发实习',
    url: '',
    claims: [
      { text: '2026.01–2026.03，做 LangChain/LangGraph 工作流开发与 RAG 方案实现', evidence: '实习经历' },
      { text: '搭过评估调试流程', evidence: '实习经历' }
    ]
  }
];

/** 出厂默认画像，对应设计文档 §3。 */
export const DEFAULT_PROFILE = {
  version: 1,
  city: '深圳',
  targetKeywords: DEFAULT_TARGET_KEYWORDS,
  blocklist: DEFAULT_BLOCKLIST,
  skills: DEFAULT_SKILLS,
  facts: DEFAULT_FACTS,

  salaryMinK: 8,
  salaryIdealK: 12,
  /** 月薪上限低于 salaryMinK 的岗位直接 skip。 */
  rejectBelowMinSalary: true,

  /** 偏好公司规模档位（BOSS 的分档文案）。 */
  preferredCompanySizes: ['20-99人', '0-20人', '100-499人'],

  /** 学历：我是本科，要求硕士及以上的直接 skip。 */
  educationLevel: 'bachelor',
  /** 经验：应届，超过这个年限的硬性要求直接 skip。 */
  maxRequiredYears: 3,

  /** 发布者身份里出现这些词，说明大概率是技术负责人直招。 */
  preferredPublisherTitles: ['CTO', '技术负责人', '技术总监', '创始人', 'CEO', '架构师', '研发经理', '技术合伙人'],

  /** 阈值，对应设计文档 §4.2。 */
  applyThreshold: 80,
  reviewThreshold: 60,

  /** 个人偏好加分/扣分，默认关，见 domain/preference.js。 */
  preference: DEFAULT_PREFERENCE
};

/** 合并用户配置和默认值，容忍旧版本存档缺字段。 */
export function normalizeProfile(saved) {
  const p = { ...DEFAULT_PROFILE, ...(saved || {}) };
  const arrays = ['targetKeywords', 'blocklist', 'skills', 'preferredCompanySizes', 'preferredPublisherTitles'];
  for (const key of arrays) {
    if (!Array.isArray(p[key]) || p[key].length === 0) p[key] = DEFAULT_PROFILE[key];
    p[key] = p[key].map((s) => String(s).trim()).filter(Boolean);
  }
  if (!Array.isArray(p.facts)) p.facts = DEFAULT_FACTS;
  p.salaryMinK = Number(p.salaryMinK) || DEFAULT_PROFILE.salaryMinK;
  p.maxRequiredYears = Number.isFinite(Number(p.maxRequiredYears))
    ? Number(p.maxRequiredYears)
    : DEFAULT_PROFILE.maxRequiredYears;
  p.applyThreshold = clampScore(p.applyThreshold, DEFAULT_PROFILE.applyThreshold);
  p.reviewThreshold = clampScore(p.reviewThreshold, DEFAULT_PROFILE.reviewThreshold);
  if (p.reviewThreshold > p.applyThreshold) p.reviewThreshold = p.applyThreshold;
  p.preference = normalizePreference(p.preference);
  return p;
}

function clampScore(value, fallback) {
  const n = Number(value);
  if (!Number.isFinite(n)) return fallback;
  return Math.min(100, Math.max(0, Math.round(n)));
}

/**
 * 事实库摊平成给模型看的纯文本。
 * 只输出 claims，note 单独作为禁止项传下去。
 */
export function factsToPromptText(facts) {
  return (facts || [])
    .map((f) => {
      const lines = [`【${f.project}】${f.url ? ' ' + f.url : ''}`];
      for (const c of f.claims || []) lines.push(`- ${c.text}（证据：${c.evidence}）`);
      if (f.note) lines.push(`- 注意：${f.note}`);
      return lines.join('\n');
    })
    .join('\n\n');
}
