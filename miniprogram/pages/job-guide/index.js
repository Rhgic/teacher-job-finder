const STEPS = [
  {
    title: "先定目标",
    desc: "明确区域、学段、学科、编制偏好，避免所有岗位都想看。",
    action: "完善求职档案",
    url: "/pages/profile-edit/index"
  },
  {
    title: "筛岗位",
    desc: "用区域、学科、关键词和保存搜索，把每天要看的岗位控制在少量候选。",
    action: "去岗位列表",
    url: "/pages/jobs/index",
    tab: true
  },
  {
    title: "核来源",
    desc: "优先看官方公告或可信本地来源，邮箱、截止日期和附件要求要回原文确认。",
    action: "看核验规则",
    url: "/pages/source-guide/index"
  },
  {
    title: "比优先级",
    desc: "把收藏岗位放到一起，对比编制、截止、来源完整度和投递风险。",
    action: "岗位对比",
    url: "/pages/job-compare/index"
  },
  {
    title: "备材料",
    desc: "身份证明、学历学位、教师资格证、普通话、报名表和岗位附件逐项核对。",
    action: "材料清单",
    url: "/pages/materials/index"
  },
  {
    title: "确认投递",
    desc: "投递前必须确认公告来源、材料、简历真实性；系统不会绕过你自动投递。",
    action: "查看投递台",
    url: "/pages/applications/index",
    tab: true
  },
  {
    title: "准备面试",
    desc: "按学科准备试讲/说课方向、结构化问题和学校画像。",
    action: "先选岗位",
    url: "/pages/jobs/index",
    tab: true
  }
]

Page({
  data: {
    steps: STEPS
  },
  openStep(event) {
    const step = this.data.steps[event.currentTarget.dataset.index]
    if (!step || !step.url) return
    if (step.tab) {
      wx.switchTab({ url: step.url })
      return
    }
    wx.navigateTo({ url: step.url })
  }
})
