const { getJob } = require("../../utils/api")
const { buildSourceReview } = require("../../utils/source-review")
const { addSubscriptionSynced, isFavorite, syncFavoritesFromRemote, toggleFavoriteSynced } = require("../../utils/store")

Page({
  data: {
    job: {},
    salaryText: "面议",
    deadlineText: "待定",
    headcountText: 1,
    emailText: "公告原文查看",
    tagClass: "gray",
    tagText: "非编",
    favoriteText: "收藏岗位",
    sourceHost: "",
    sourceHostText: "暂无公告域名",
    sourceText: "公告原文待补充",
    sourceStatusText: "暂无来源",
    sourceStatusClass: "gray",
    emailRiskText: "邮箱待确认",
    deadlineRiskText: "截止待确认",
    riskTips: [],
    isExpired: false,
    applyButtonText: "去核对材料"
  },
  async onLoad(options) {
    await syncFavoritesFromRemote()
    const job = await getJob(options.id)
    const salaryText = this.formatSalary(job.salary_min, job.salary_max)
    const meta = [job.school_name, job.district, job.stage, job.subject].filter(Boolean).join(" · ")
    const sourceReview = buildSourceReview(job)
    const isExpired = this.isExpired(job.deadline_at || job.deadline)
    this.setData({
      job,
      metaText: meta || "岗位信息待补全",
      salaryText,
      deadlineText: job.deadline_at ? String(job.deadline_at).slice(0, 10) : "待定",
      headcountText: job.headcount || 1,
      emailText: job.apply_email || "公告原文查看",
      tagClass: job.is_establishment ? "green" : "gray",
      tagText: job.is_establishment ? "有编制" : "非编",
      favoriteText: isFavorite(job.id) ? "已收藏" : "收藏岗位",
      isExpired,
      applyButtonText: isExpired ? "已截止，查看公告" : "去核对材料",
      ...sourceReview
    })
  },
  isExpired(deadline) {
    if (!deadline) return false
    const date = new Date(`${String(deadline).slice(0, 10)}T23:59:59`)
    if (Number.isNaN(date.getTime())) return false
    return date.getTime() < Date.now()
  },
  formatSalary(min, max) {
    if (min && max) return `${Math.round(min / 1000)}k-${Math.round(max / 1000)}k`
    if (min) return `${Math.round(min / 1000)}k起`
    if (max) return `最高${Math.round(max / 1000)}k`
    return "面议"
  },
  goApply() {
    if (this.data.isExpired) {
      wx.showModal({
        title: "这个岗位已经截止",
        content: "先别投递了。你可以复制公告信息，回到官方来源确认是否有补报名或延期通知。",
        confirmText: "复制信息",
        cancelText: "知道了",
        success: (res) => {
          if (res.confirm) this.copySource()
        }
      })
      return
    }
    wx.navigateTo({ url: `/pages/apply-confirm/index?id=${this.data.job.id}` })
  },
  toggleFavorite() {
    const favorited = toggleFavoriteSynced(this.data.job)
    this.setData({ favoriteText: favorited ? "已收藏" : "收藏岗位" })
    wx.showToast({ title: favorited ? "已收藏" : "已取消", icon: "none" })
  },
  async subscribeSimilar() {
    const job = this.data.job
    const rule = {
      id: `job-rule-${Date.now()}`,
      name: `${job.district || "深圳"}${job.subject || "教师"}岗位`,
      district: job.district || "全深圳",
      stage: job.stage || "不限",
      subject: job.subject || "不限",
      bianzhi: job.is_establishment ? "优先编制" : "不限",
      enabled: true
    }
    const result = await addSubscriptionSynced(rule)
    wx.showToast({ title: result.synced ? "已同步订阅" : "已加入订阅", icon: result.synced ? "success" : "none" })
  },
  goInterviewPrep() {
    wx.navigateTo({ url: `/pages/interview-prep/index?id=${this.data.job.id}` })
  },
  goSchoolProfile() {
    const school = encodeURIComponent(this.data.job.school_name || "")
    wx.navigateTo({ url: `/pages/school-profile/index?school=${school}` })
  },
  goSourceGuide() {
    wx.navigateTo({ url: "/pages/source-guide/index" })
  },
  copySource() {
    const job = this.data.job || {}
    const text = job.source_url || job.apply_email || `${job.school_name || ""} ${job.title || ""}`.trim()
    if (!text) {
      wx.showToast({ title: "暂无可复制信息", icon: "none" })
      return
    }
    wx.setClipboardData({
      data: text,
      success() {
        wx.showToast({ title: "已复制", icon: "success" })
      }
    })
  }
})
