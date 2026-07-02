const { getJobs, getMatches, runPipeline } = require("../../utils/api")

function toList(value) {
  return Array.isArray(value) ? value.filter(Boolean) : []
}

function formatMatch(match) {
  const matchedPoints = toList(match.matched_points)
  const gaps = toList(match.gaps)
  const score = Number(match.llm_score || 0)
  return {
    ...match,
    scoreText: score > 0 ? `${score}` : "待评估",
    reasonText: match.reason || match.match_reason || "岗位与当前求职目标匹配，建议继续核对公告。",
    matchedPoints,
    gaps,
    gapTone: gaps.some((item) => String(item).includes("缺口") || String(item).includes("未")) ? "warn" : "green",
    coverLetterPreview: match.cover_letter || "生成求职信草稿需要先配置真实模型或完善简历摘要。"
  }
}

Page({
  data: {
    matches: [],
    isEmpty: false,
    topScoreText: "-",
    matchCountText: "0",
    running: false
  },
  onShow() {
    this.loadMatches()
  },
  async loadMatches() {
    const jobs = await getJobs()
    const jobMap = jobs.reduce((map, job) => {
      map[job.id] = job
      return map
    }, {})
    const matches = await getMatches()
    const merged = matches
      .map((match) => ({
        ...match,
        job: match.job || jobMap[match.job_id]
      }))
      .filter((match) => match.job)
      .map(formatMatch)
    this.setData({
      matches: merged,
      isEmpty: merged.length === 0,
      topScoreText: merged[0] ? merged[0].scoreText : "-",
      matchCountText: `${merged.length}`
    })
  },
  async refreshRecommendations() {
    if (this.data.running) return
    this.setData({ running: true })
    wx.showLoading({ title: "匹配中" })
    try {
      await runPipeline()
      await this.loadMatches()
      wx.showToast({ title: "已刷新", icon: "success" })
    } catch (error) {
      wx.showToast({ title: "使用演示推荐", icon: "none" })
      await this.loadMatches()
    } finally {
      wx.hideLoading()
      this.setData({ running: false })
    }
  },
  openProfile() {
    wx.navigateTo({ url: "/pages/profile-edit/index" })
  },
  openJob(event) {
    const id = event.currentTarget.dataset.id
    if (id) wx.navigateTo({ url: `/pages/job-detail/index?id=${id}` })
  },
  openApply(event) {
    const id = event.currentTarget.dataset.id
    if (id) wx.navigateTo({ url: `/pages/apply-confirm/index?id=${id}` })
  }
})
