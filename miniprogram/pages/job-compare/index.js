const { getJobs } = require("../../utils/api")
const { buildSourceReview } = require("../../utils/source-review")
const { getFavorites, syncFavoritesFromRemote } = require("../../utils/store")

function daysUntil(dateText) {
  if (!dateText) return null
  const date = new Date(`${String(dateText).slice(0, 10)}T23:59:59`)
  if (Number.isNaN(date.getTime())) return null
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  return Math.ceil((date.getTime() - today.getTime()) / 86400000)
}

function scoreJob(job) {
  let score = 40
  const source = buildSourceReview(job)
  const daysLeft = daysUntil(job.deadline_at || job.deadline)
  if (job.is_establishment) score += 15
  if (job.recruiter_email || job.apply_email) score += 10
  if (source.sourceStatusClass === "ok") score += 18
  if (source.sourceStatusClass === "pending") score += 8
  if (daysLeft !== null && daysLeft >= 0 && daysLeft <= 7) score += 8
  if (daysLeft !== null && daysLeft > 7 && daysLeft <= 30) score += 5
  if (!job.deadline_at && !job.deadline) score -= 6
  return Math.max(0, Math.min(100, score))
}

function normalize(job) {
  const deadline = job.deadline_at || job.deadline || ""
  const daysLeft = daysUntil(deadline)
  const source = buildSourceReview(job)
  const risks = []
  if (!job.source_url) risks.push("来源待确认")
  if (!deadline) risks.push("截止待确认")
  if (!job.recruiter_email && !job.apply_email) risks.push("邮箱待确认")
  return {
    ...job,
    compareScore: scoreJob(job),
    deadlineText: deadline ? String(deadline).slice(0, 10) : "待确认",
    daysLeftText: daysLeft === null ? "待确认" : daysLeft < 0 ? "已过期" : `${daysLeft} 天`,
    bianzhiText: job.is_establishment ? "有编制" : "看公告",
    sourceText: source.sourceStatusText,
    sourceClass: source.sourceStatusClass,
    riskText: risks.length ? risks.join("、") : "信息较完整"
  }
}

Page({
  data: {
    jobs: [],
    sourceText: "收藏岗位",
    totalCount: 0,
    bestJob: null,
    isEmpty: false
  },
  onShow() {
    this.load()
  },
  async load() {
    const favorites = await syncFavoritesFromRemote()
    let sourceText = "收藏岗位"
    let candidates = favorites
    if (!candidates.length) {
      candidates = (await getJobs()).slice(0, 6)
      sourceText = "最近岗位"
    }
    const jobs = candidates
      .map(normalize)
      .sort((a, b) => b.compareScore - a.compareScore)
      .slice(0, 6)
    this.setData({
      jobs,
      sourceText,
      totalCount: jobs.length,
      bestJob: jobs[0] || null,
      isEmpty: jobs.length === 0
    })
  },
  openJob(event) {
    const id = event.currentTarget.dataset.id
    if (id) wx.navigateTo({ url: `/pages/job-detail/index?id=${id}` })
  },
  openFavorites() {
    wx.navigateTo({ url: "/pages/favorites/index" })
  }
})
