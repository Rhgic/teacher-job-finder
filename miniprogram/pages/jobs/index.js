const { getJobs } = require("../../utils/api")
const { buildSourceReview } = require("../../utils/source-review")
const { getSavedSearches, saveSavedSearchesSynced, syncSavedSearchesFromRemote } = require("../../utils/store")

const SHENZHEN_DISTRICTS = [
  "罗湖区",
  "福田区",
  "南山区",
  "盐田区",
  "宝安区",
  "龙岗区",
  "龙华区",
  "坪山区",
  "光明区",
  "大鹏新区",
  "深汕特别合作区"
]

const DEFAULT_SUBJECTS = [
  "语文",
  "数学",
  "英语",
  "物理",
  "化学",
  "生物",
  "历史",
  "地理",
  "政治",
  "音乐",
  "体育",
  "美术",
  "信息技术",
  "科学",
  "心理"
]

Page({
  data: {
    jobs: [],
    filteredJobs: [],
    districts: ["全部"],
    stages: ["全部"],
    subjects: ["全部"],
    district: "",
    stage: "",
    subject: "",
    keyword: "",
    onlyBianzhi: false,
    includeExpired: false,
    rangeModeText: "当前可投",
    districtText: "不限",
    stageText: "不限",
    subjectText: "不限",
    bianzhiClass: "",
    filtersOpen: false,
    filterSummary: "未筛选，显示全部岗位",
    filteredCount: 0,
    isEmpty: false,
    savedSearches: []
  },
  toggleFilters() {
    this.setData({ filtersOpen: !this.data.filtersOpen })
  },
  async onShow() {
    this.setData({ savedSearches: getSavedSearches() })
    this.setData({ savedSearches: await syncSavedSearchesFromRemote() })
    this.loadJobs()
  },
  async loadJobs() {
    const jobs = await getJobs({ include_expired: this.data.includeExpired })
    const uniq = (key) => ["全部"].concat([...new Set(jobs.map((item) => item[key]).filter(Boolean))])
    const districts = ["全部"].concat([...new Set(SHENZHEN_DISTRICTS.concat(jobs.map((item) => item.district).filter(Boolean)))])
    const subjects = ["全部"].concat([...new Set(DEFAULT_SUBJECTS.concat(jobs.map((item) => item.subject).filter(Boolean)))])
    this.setData({
      jobs,
      districts,
      stages: uniq("stage"),
      subjects
    })
    this.applyFilters()
  },
  onDistrictChange(event) {
    const value = this.data.districts[event.detail.value]
    this.setData({
      district: value === "全部" ? "" : value,
      districtText: value === "全部" ? "不限" : value
    })
    this.applyFilters()
  },
  onStageChange(event) {
    const value = this.data.stages[event.detail.value]
    this.setData({
      stage: value === "全部" ? "" : value,
      stageText: value === "全部" ? "不限" : value
    })
    this.applyFilters()
  },
  onSubjectChange(event) {
    const value = this.data.subjects[event.detail.value]
    this.setData({
      subject: value === "全部" ? "" : value,
      subjectText: value === "全部" ? "不限" : value
    })
    this.applyFilters()
  },
  toggleBianzhi() {
    const onlyBianzhi = !this.data.onlyBianzhi
    this.setData({
      onlyBianzhi,
      bianzhiClass: onlyBianzhi ? "active" : ""
    })
    this.applyFilters()
  },
  toggleExpiredMode() {
    const includeExpired = !this.data.includeExpired
    this.setData({
      includeExpired,
      rangeModeText: includeExpired ? "含已截止" : "当前可投"
    })
    this.loadJobs()
  },
  onKeywordInput(event) {
    this.setData({ keyword: event.detail.value || "" })
    this.applyFilters()
  },
  clearKeyword() {
    this.setData({ keyword: "" })
    this.applyFilters()
  },
  resetFilters() {
    this.setData({
      district: "",
      stage: "",
      subject: "",
      keyword: "",
      onlyBianzhi: false,
      includeExpired: false,
      rangeModeText: "当前可投",
      districtText: "不限",
      stageText: "不限",
      subjectText: "不限",
      bianzhiClass: ""
    })
    this.loadJobs()
  },
  async saveCurrentSearch() {
    const { district, stage, subject, keyword, onlyBianzhi, includeExpired } = this.data
    if (!district && !stage && !subject && !keyword && !onlyBianzhi && !includeExpired) {
      wx.showToast({ title: "先筛选一个条件", icon: "none" })
      return
    }
    const label = [
      district || "全深圳",
      stage || "不限学段",
      subject || "不限学科",
      onlyBianzhi ? "编制" : "",
      includeExpired ? "含已截止" : "",
      keyword ? `搜:${keyword}` : ""
    ].filter(Boolean).join(" · ")
    const search = { id: `search-${Date.now()}`, label, district, stage, subject, keyword, onlyBianzhi, includeExpired }
    const deduped = getSavedSearches().filter((item) => item.label !== label)
    const savedSearches = await saveSavedSearchesSynced([search].concat(deduped))
    this.setData({ savedSearches })
    wx.showToast({ title: "已保存搜索", icon: "success" })
  },
  applySavedSearch(event) {
    const id = event.currentTarget.dataset.id
    const search = this.data.savedSearches.find((item) => item.id === id)
    if (!search) return
    this.setData({
      district: search.district || "",
      stage: search.stage || "",
      subject: search.subject || "",
      keyword: search.keyword || "",
      onlyBianzhi: Boolean(search.onlyBianzhi),
      includeExpired: Boolean(search.includeExpired),
      rangeModeText: search.includeExpired ? "含已截止" : "当前可投",
      districtText: search.district || "不限",
      stageText: search.stage || "不限",
      subjectText: search.subject || "不限",
      bianzhiClass: search.onlyBianzhi ? "active" : ""
    })
    this.loadJobs()
  },
  applyFilters() {
    const { jobs, district, stage, subject, keyword, onlyBianzhi, includeExpired } = this.data
    const normalizedKeyword = keyword.trim().toLowerCase()
    const filteredJobs = jobs.filter((job) => {
      if (!includeExpired && this.isExpired(job.deadline_at || job.deadline)) return false
      if (district && job.district !== district) return false
      if (stage && job.stage !== stage) return false
      if (subject && job.subject !== subject) return false
      if (normalizedKeyword) {
        const haystack = [
          job.title,
          job.school_name,
          job.district,
          job.stage,
          job.subject,
          job.description,
          job.jd
        ].filter(Boolean).join(" ").toLowerCase()
        if (!haystack.includes(normalizedKeyword)) return false
      }
      if (onlyBianzhi && !job.is_establishment) return false
      return true
    }).map((job) => {
      const min = job.salary_min ? `${Math.round(job.salary_min / 1000)}k` : ""
      const max = job.salary_max ? `${Math.round(job.salary_max / 1000)}k` : ""
      const date = job.deadline_at || job.deadline || ""
      const sourceReview = buildSourceReview(job)
      const isExpired = this.isExpired(date)
      const normalized = Object.assign({}, job)
      normalized.isExpired = isExpired
      normalized.cardClass = isExpired ? "expired" : ""
      normalized.salaryText = min && max ? `${min}-${max}` : min ? `${min}+` : "面议"
      normalized.deadlineShort = date ? String(date).slice(5, 10).replace("-", "/") : "待定"
      normalized.deadlineTagText = isExpired ? `${normalized.deadlineShort} 已截止` : `${normalized.deadlineShort} 截止`
      normalized.statusText = isExpired ? "历史参考" : job.is_establishment ? "优先核对" : "看公告"
      normalized.sourceStatusText = sourceReview.sourceStatusText
      normalized.sourceStatusClass = sourceReview.sourceStatusClass
      normalized.sourceHostText = sourceReview.sourceHostText
      return normalized
    })
    const hasFilter = Boolean(district || stage || subject || keyword || onlyBianzhi || this.data.includeExpired)
    const summaryParts = [
      district || "全深圳",
      stage || "不限学段",
      subject || "不限学科",
      onlyBianzhi ? "只看编制" : "",
      this.data.includeExpired ? "含已截止" : "",
      keyword ? `搜:${keyword}` : ""
    ].filter(Boolean)
    this.setData({
      filteredJobs,
      filteredCount: filteredJobs.length,
      isEmpty: filteredJobs.length === 0,
      filterSummary: hasFilter ? summaryParts.join(" · ") : "未筛选，显示全部岗位"
    })
  },
  isExpired(deadline) {
    if (!deadline) return false
    const date = new Date(`${String(deadline).slice(0, 10)}T23:59:59`)
    if (Number.isNaN(date.getTime())) return false
    return date.getTime() < Date.now()
  },
  async refreshJobs() {
    wx.showLoading({ title: "刷新中" })
    try {
      await this.loadJobs()
      wx.showToast({ title: "已刷新", icon: "success" })
    } catch (error) {
      wx.showToast({ title: "刷新失败，稍后再试", icon: "none" })
    } finally {
      wx.hideLoading()
    }
  },
  openJob(event) {
    const id = event.currentTarget.dataset.id
    if (id) {
      wx.navigateTo({ url: `/pages/job-detail/index?id=${id}` })
    }
  }
})
