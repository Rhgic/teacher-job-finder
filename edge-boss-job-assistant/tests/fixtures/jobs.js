/** 测试用岗位快照。文案照着 BOSS 页面的真实写法编，别改成理想格式。 */

import { emptySnapshot } from '../../src/domain/job.js';

export function makeJob(overrides = {}) {
  return { ...emptySnapshot(), ...overrides };
}

/** 典型好岗位：小公司 AI 应用开发，技术负责人发布。 */
export const GOOD_AI_JOB = makeJob({
  jobTitle: 'AI应用开发工程师（Agent方向）',
  companyName: '深圳某某智能科技有限公司',
  jobUrl: 'https://www.zhipin.com/job_detail/aaa111.html',
  salaryText: '10-15K·13薪',
  cityText: '深圳',
  districtText: '南山区',
  experienceText: '经验不限',
  educationText: '本科',
  companySizeText: '20-99人',
  companyIndustry: '人工智能服务',
  publisherTitle: '陈某·技术负责人',
  tags: ['Python', 'LLM', 'RAG'],
  jobDescription: `岗位职责：
1. 负责基于大模型的 Agent 应用开发，使用 Function Calling 编排工具调用；
2. 参与 RAG 知识库问答系统的检索与重排优化；
3. 使用 Python / FastAPI 开发后端服务，配合 Docker 部署。
任职要求：
1. 熟悉 Python，了解 LLM 应用开发；
2. 有 RAG 或 Agent 相关项目经验优先；
3. 本科及以上学历。`
});

/** 挂 AI 名义的销售岗。 */
export const FAKE_AI_SALES_JOB = makeJob({
  jobTitle: 'AI产品销售顾问',
  companyName: '某某教育科技有限公司',
  jobUrl: 'https://www.zhipin.com/job_detail/bbb222.html',
  salaryText: '6-20K',
  cityText: '深圳',
  experienceText: '经验不限',
  educationText: '大专',
  companySizeText: '100-499人',
  publisherTitle: '李某·HR',
  jobDescription: '负责 AI 课程的招生与销售转化，完成业绩指标考核，电话邀约意向客户到店。'
});

/** 外包驻场，职位名看不出来，JD 里才露馅。 */
export const OUTSOURCE_JOB = makeJob({
  jobTitle: 'Python开发工程师',
  companyName: '某某信息技术服务有限公司',
  jobUrl: 'https://www.zhipin.com/job_detail/ccc333.html',
  salaryText: '9-14K',
  cityText: '深圳',
  experienceText: '1-3年',
  educationText: '本科',
  companySizeText: '500-999人',
  publisherTitle: '王某·招聘专员',
  jobDescription: '本岗位为外包项目，需驻场开发，派驻甲方银行客户现场办公，负责 Python 数据处理脚本编写。'
});

/** 硬性门槛不达标：要 3 年以上 + 硕士。 */
export const OVER_QUALIFIED_JOB = makeJob({
  jobTitle: '大模型算法工程师',
  companyName: '某某人工智能研究院',
  jobUrl: 'https://www.zhipin.com/job_detail/ddd444.html',
  salaryText: '30-50K',
  cityText: '深圳',
  experienceText: '5-10年',
  educationText: '硕士',
  companySizeText: '100-499人',
  publisherTitle: '赵某·算法总监',
  jobDescription: '负责大模型预训练与微调，要求有分布式训练经验。'
});

/** 城市不对。 */
export const WRONG_CITY_JOB = makeJob({
  ...GOOD_AI_JOB,
  jobUrl: 'https://www.zhipin.com/job_detail/eee555.html',
  cityText: '杭州',
  districtText: '余杭区'
});

/** BOSS 岗位页大致的可见文本，用来测文本兜底那一层。 */
export const PAGE_TEXT_SAMPLE = `AI应用开发工程师
10-15K·13薪
深圳 · 南山区 · 经验不限 · 本科
某某智能科技
已认证 · 20-99人 · 人工智能服务
陈某 · 技术负责人 · 刚刚活跃`;
