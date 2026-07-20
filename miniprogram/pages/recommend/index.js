const { getJobs, getMatches } = require("../../utils/api")

Page({
  data: {
    matches: [],
    isEmpty: false
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
    this.setData({
      matches: merged,
      isEmpty: merged.length === 0
    })
  },
  async refreshRecommendations() {
    wx.showLoading({ title: "刷新中" })
    try {
      await this.loadMatches()
      wx.showToast({ title: "已刷新", icon: "success" })
    } catch (error) {
      wx.showToast({ title: "使用演示推荐", icon: "none" })
      await this.loadMatches()
    } finally {
      wx.hideLoading()
    }
  },
  openProfile() {
    wx.navigateTo({ url: "/pages/profile-edit/index" })
  }
})
