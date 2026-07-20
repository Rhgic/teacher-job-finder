const { getJobs } = require("../../utils/api")

function daysUntil(dateText) {
  if (!dateText) return null
  const date = new Date(`${String(dateText).slice(0, 10)}T23:59:59`)
  if (Number.isNaN(date.getTime())) return null
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  return Math.ceil((date.getTime() - today.getTime()) / 86400000)
}

function normalize(job) {
  const deadline = job.deadline_at || job.deadline || ""
  const daysLeft = daysUntil(deadline)
  let urgency = "待定"
  if (daysLeft !== null && daysLeft < 0) urgency = "已过期"
  else if (daysLeft !== null && daysLeft <= 7) urgency = "快截止"
  else if (daysLeft !== null && daysLeft <= 30) urgency = "近期"
  return {
    ...job,
    deadlineText: deadline ? String(deadline).slice(0, 10) : "待定",
    daysLeftText: daysLeft === null ? "待定" : daysLeft < 0 ? "已过期" : `${daysLeft}天`,
    urgency
  }
}

Page({
  data: {
    urgentJobs: [],
    upcomingJobs: [],
    unknownJobs: [],
    totalCount: 0
  },
  onShow() {
    this.load()
  },
  async load() {
    const jobs = (await getJobs()).map(normalize)
    const activeJobs = jobs.filter((job) => job.urgency !== "已过期")
    this.setData({
      urgentJobs: activeJobs.filter((job) => job.urgency === "快截止"),
      upcomingJobs: activeJobs.filter((job) => job.urgency === "近期"),
      unknownJobs: activeJobs.filter((job) => job.urgency === "待定"),
      totalCount: activeJobs.length
    })
  },
  openJob(event) {
    const id = event.currentTarget.dataset.id
    if (id) wx.navigateTo({ url: `/pages/job-detail/index?id=${id}` })
  }
})
