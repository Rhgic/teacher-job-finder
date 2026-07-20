const { buildSourceReview } = require("../../utils/source-review")

Component({
  properties: {
    job: {
      type: Object,
      value: {}
    },
    score: {
      type: Number,
      value: 0
    },
    reason: {
      type: String,
      value: ""
    },
    applyText: {
      type: String,
      value: "确认投递"
    }
  },
  observers: {
    "job, score, reason": function () {
      this.updateComputed()
    }
  },
  lifetimes: {
    attached() {
      this.updateComputed()
    }
  },
  methods: {
    updateComputed() {
      const job = this.data.job || {}
      const deadline = job.deadline_at ? String(job.deadline_at).slice(5, 10).replace("-", "/") : "待定"
      const meta = [job.district, job.stage, job.subject].filter(Boolean).join(" · ") || "岗位信息待补全"
      const score = Number(this.data.score)
      const sourceReview = buildSourceReview(job)
      this.setData({
        salaryText: this.formatSalary(job.salary_min, job.salary_max),
        headcountText: job.headcount || 1,
        deadlineText: deadline,
        metaText: meta,
        showReason: Boolean(this.data.reason),
        scoreText: score > 0 ? score : "待评估",
        tagClass: job.is_establishment ? "green" : "gray",
        tagText: job.is_establishment ? "有编制" : "非编/待确认",
        sourceStatusText: sourceReview.sourceStatusText,
        sourceStatusClass: sourceReview.sourceStatusClass
      })
    },
    formatSalary(min, max) {
      if (min && max) return `${Math.round(min / 1000)}k-${Math.round(max / 1000)}k`
      if (min) return `${Math.round(min / 1000)}k起`
      if (max) return `最高${Math.round(max / 1000)}k`
      return "面议"
    },
    noop() {},
    onOpen() {
      const id = this.data.job.id
      wx.navigateTo({ url: `/pages/job-detail/index?id=${id}` })
    },
    onApply() {
      const id = this.data.job.id
      wx.navigateTo({ url: `/pages/apply-confirm/index?id=${id}` })
    }
  }
})
