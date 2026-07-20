const { getApplications, getJobs, getProfile } = require("../../utils/api")
const {
  getMaterials,
  getSubscriptions,
  syncLocalApplicationsFromRemote,
  syncNotificationPreferencesFromRemote,
  syncResumesFromRemote,
  syncSubscriptionsFromRemote
} = require("../../utils/store")

function daysUntil(dateText) {
  if (!dateText) return null
  const date = new Date(`${String(dateText).slice(0, 10)}T23:59:59`)
  if (Number.isNaN(date.getTime())) return null
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  return Math.ceil((date.getTime() - today.getTime()) / 86400000)
}

function statusText(status) {
  const map = {
    pending: "待发送",
    sent: "已发送",
    delivered: "已送达",
    failed: "发送失败",
    bounced: "已退信",
    "待处理": "待处理",
    "已面试": "已面试",
    "已录用": "已录用",
    "未通过": "未通过"
  }
  return map[status] || status || "待处理"
}

function buildDeadlineTasks(jobs, daysBefore) {
  const windowDays = Math.max(1, Number(daysBefore || 3))
  return jobs
    .map((job) => {
      const deadline = job.deadline_at || job.deadline || ""
      const daysLeft = daysUntil(deadline)
      if (daysLeft === null || daysLeft < 0 || daysLeft > windowDays) return null
      return {
        id: `deadline-${job.id}`,
        type: "deadline",
        level: daysLeft <= 2 ? "urgent" : "soon",
        title: daysLeft === 0 ? "今天截止" : `${daysLeft} 天后截止`,
        desc: `${job.school_name || "学校"} · ${job.stage || "学段待确认"} · ${job.subject || "学科待确认"}`,
        action: "查看岗位",
        jobId: job.id
      }
    })
    .filter(Boolean)
}

function buildApplicationTasks(records) {
  return records
    .map((item) => {
      const text = statusText(item.status)
      if (!["待处理", "待发送", "发送失败", "已退信", "已面试", "未通过"].includes(text)) return null
      return {
        id: `application-${item.id}`,
        type: "application",
        level: text === "发送失败" || text === "已退信" ? "urgent" : "normal",
        title: text === "待发送" ? "有投递待确认" : `投递状态：${text}`,
        desc: item.school_name || item.job_title || item.recipient_email || "投递记录",
        action: "去投递台"
      }
    })
    .filter(Boolean)
}

function buildProfileTasks(profile, resumes, subscriptions, materials, preferences) {
  const tasks = []
  const subjects = profile.target_subjects || []
  const activeRules = subscriptions.filter((item) => item.enabled !== false)
  const materialItems = Array.isArray(materials) ? materials.flatMap((group) => group.items || []) : []
  const hasUncheckedMaterials = materialItems.length > 0 && materialItems.some((item) => !item.checked)
  if (!profile.email) {
    tasks.push({
      id: "profile-email",
      type: "profile",
      level: "normal",
      title: "补充求职邮箱",
      desc: "后续投递和回信都需要一个稳定邮箱。",
      action: "去档案"
    })
  }
  if (subjects.length === 0) {
    tasks.push({
      id: "profile-subject",
      type: "profile",
      level: "normal",
      title: "选择目标学科",
      desc: "推荐会优先按学科和学段筛选。",
      action: "去档案"
    })
  }
  if (!resumes.length) {
    tasks.push({
      id: "resume-empty",
      type: "resume",
      level: "normal",
      title: "准备一份默认简历",
      desc: "投递前需要可核对的真实材料。",
      action: "去简历"
    })
  }
  if (!activeRules.length) {
    tasks.push({
      id: "rule-empty",
      type: "rule",
      level: "normal",
      title: "开启岗位订阅",
      desc: "至少保留一条深圳教师岗位订阅。",
      action: "去订阅"
    })
  }
  if (preferences.materials !== false && hasUncheckedMaterials) {
    tasks.push({
      id: "materials-unchecked",
      type: "materials",
      level: "normal",
      title: "核对投递材料",
      desc: "还有证书、附件或报名表没有勾选完成。",
      action: "去清单"
    })
  }
  return tasks
}

Page({
  data: {
    loading: true,
    tasks: [],
    urgentCount: 0,
    deadlineCount: 0,
    pendingCount: 0,
    profileCount: 0,
    preferenceText: "按提醒设置筛选",
    emptyText: "今天没有必须处理的提醒"
  },
  onShow() {
    this.load()
  },
  async load() {
    this.setData({ loading: true })
    const [jobs, remoteApplications, profile] = await Promise.all([
      getJobs(),
      getApplications(),
      getProfile()
    ])
    const [localApplications, preferencesResult] = await Promise.all([
      syncLocalApplicationsFromRemote(),
      syncNotificationPreferencesFromRemote()
    ])
    const preferences = preferencesResult.value || {}
    const resumesResult = await syncResumesFromRemote()
    const resumes = resumesResult.list || []
    const subscriptionsResult = await syncSubscriptionsFromRemote()
    const subscriptions = subscriptionsResult.list || getSubscriptions()
    const materials = getMaterials()
    const deadlineTasks = preferences.deadline === false ? [] : buildDeadlineTasks(jobs, preferences.days_before)
    const applicationTasks = preferences.application === false ? [] : buildApplicationTasks(localApplications.concat(remoteApplications || []))
    const profileTasks = buildProfileTasks(profile, resumes, subscriptions, materials, preferences)
    const tasks = deadlineTasks.concat(applicationTasks, profileTasks)
    this.setData({
      loading: false,
      tasks,
      urgentCount: tasks.filter((item) => item.level === "urgent").length,
      deadlineCount: deadlineTasks.length,
      pendingCount: applicationTasks.length,
      profileCount: profileTasks.length,
      preferenceText: `按${preferencesResult.source || "本地"}提醒设置筛选 · 截止前 ${preferences.days_before || 3} 天`
    })
  },
  openTask(event) {
    const item = this.data.tasks.find((task) => task.id === event.currentTarget.dataset.id)
    if (!item) return
    if (item.jobId) {
      wx.navigateTo({ url: `/pages/job-detail/index?id=${item.jobId}` })
      return
    }
    const routes = {
      application: "/pages/applications/index",
      profile: "/pages/profile-edit/index",
      resume: "/pages/resumes/index",
      rule: "/pages/subscriptions/index",
      materials: "/pages/materials/index"
    }
    const url = routes[item.type]
    if (url) wx.navigateTo({ url })
  }
})
