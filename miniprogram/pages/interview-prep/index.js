const { getJob } = require("../../utils/api")

const SUBJECT_PROMPTS = {
  语文: ["文本解读与朗读设计", "作文讲评或阅读方法", "传统文化与课堂互动"],
  数学: ["概念引入与例题梯度", "学生易错点追问", "板书推导过程"],
  英语: ["听说活动设计", "词汇语境教学", "课堂英文指令"],
  体育: ["热身和安全保护", "专项动作分解", "分层训练与体能安排"],
  音乐: ["节奏/旋律体验", "示范演唱或器乐片段", "课堂参与设计"],
  美术: ["作品赏析", "创作步骤示范", "材料工具安全"],
  信息技术: ["任务驱动", "操作演示", "学生作品评价"],
  物理: ["实验现象引入", "概念建模", "生活情境迁移"],
  化学: ["实验安全", "现象观察", "微观解释"],
  生物: ["图示讲解", "探究活动", "生命观念表达"]
}

Page({
  data: {
    job: {},
    metaText: "",
    trialTopics: [],
    interviewQuestions: [],
    materialChecklist: []
  },
  async onLoad(options) {
    const job = await getJob(options.id)
    const subject = job.subject || "教师"
    const stage = job.stage || "对应学段"
    const prompts = SUBJECT_PROMPTS[subject] || ["课堂导入设计", "重难点讲解", "学生互动与评价"]
    this.setData({
      job,
      metaText: [job.school_name, job.district, stage, subject].filter(Boolean).join(" · "),
      trialTopics: prompts.map((item) => `${stage}${subject}：${item}`),
      interviewQuestions: [
        `为什么选择${job.school_name || "这所学校"}？`,
        `如果学生课堂参与度不高，你会怎么调整？`,
        `你如何证明自己适合${stage}${subject}岗位？`,
        "如果家长对教学安排有疑问，你会如何沟通？"
      ],
      materialChecklist: [
        "身份证、学历学位证明、教师资格证",
        "普通话证书、获奖证书、职称或培训证明",
        "针对该岗位调整后的简历和求职信",
        "公告原文要求的报名表、承诺书或附件"
      ]
    })
  }
})
