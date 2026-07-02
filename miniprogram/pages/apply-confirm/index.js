const { createApplication, getJob } = require("../../utils/api")
const { buildSourceReview } = require("../../utils/source-review")
const { addLocalApplicationSynced, syncResumesFromRemote } = require("../../utils/store")

Page({
  data: {
    job: {},
    resumes: ["深圳教师求职简历", "体育教师专项简历"],
    templates: ["标准求职信", "体育教师求职信"],
    selectedResume: "深圳教师求职简历",
    selectedTemplate: "标准求职信",
    coverLetter: "",
    checks: {
      source: false,
      materials: false,
      resume: false
    },
    canApply: false,
    sourceStatusText: "暂无来源",
    sourceStatusClass: "gray",
    emailRiskText: "邮箱待确认",
    deadlineRiskText: "截止待确认",
    isExpired: false,
    applyButtonText: "确认投递"
  },
  async onLoad(options) {
    const [job, resumesResult] = await Promise.all([
      getJob(options.id),
      syncResumesFromRemote()
    ])
    const resumes = (resumesResult.list || []).map((item) => item.name || item.file_name).filter(Boolean)
    const selectedResume = resumes[0] || this.data.selectedResume
    const sourceReview = buildSourceReview(job)
    const isExpired = this.isExpired(job.deadline_at || job.deadline)
    this.setData({
      job,
      resumes: resumes.length ? resumes : this.data.resumes,
      selectedResume,
      sourceStatusText: sourceReview.sourceStatusText,
      sourceStatusClass: sourceReview.sourceStatusClass,
      emailRiskText: sourceReview.emailRiskText,
      deadlineRiskText: sourceReview.deadlineRiskText,
      isExpired,
      applyButtonText: isExpired ? "已截止，不能确认投递" : "确认投递",
      coverLetter: `尊敬的${job.school_name || "学校"}招聘负责人：您好！我希望应聘贵校${job.subject || ""}教师岗位。我会结合个人教学经历、班级管理能力与岗位要求，认真完成课堂教学、学生培养和校园活动组织工作。期待获得进一步沟通机会。`
    })
  },
  isExpired(deadline) {
    if (!deadline) return false
    const date = new Date(`${String(deadline).slice(0, 10)}T23:59:59`)
    if (Number.isNaN(date.getTime())) return false
    return date.getTime() < Date.now()
  },
  onResumeChange(event) {
    this.setData({ selectedResume: this.data.resumes[event.detail.value] })
  },
  onTemplateChange(event) {
    this.setData({ selectedTemplate: this.data.templates[event.detail.value] })
  },
  onLetterInput(event) {
    this.setData({ coverLetter: event.detail.value })
  },
  toggleCheck(event) {
    const key = event.currentTarget.dataset.key
    const checks = {
      ...this.data.checks,
      [key]: !this.data.checks[key]
    }
    this.setData({
      checks,
      canApply: Object.keys(checks).every((item) => checks[item])
    })
  },
  confirmApply() {
    const job = this.data.job || {}
    if (this.data.isExpired) {
      wx.showModal({
        title: "已经过截止日期",
        content: "为了避免误投，这里不会写入确认投递。请回公告原文确认是否延期或补报名。",
        showCancel: false
      })
      return
    }
    if (!this.data.canApply) {
      wx.showToast({ title: "先完成三项核对", icon: "none" })
      return
    }
    if (!job.apply_email) {
      wx.showModal({
        title: "这个岗位还不能直接投",
        content: "后端没有解析到招聘邮箱。你可以先点岗位详情里的来源链接去公告原文确认投递方式。",
        showCancel: false
      })
      return
    }
    wx.showModal({
      title: "确认投递",
      content: "确认后会写入投递记录。当前开发模式默认不真实发邮件，避免误投。",
      confirmText: "确认",
      success: async (res) => {
        if (res.confirm) {
          wx.showLoading({ title: "提交中" })
          try {
            await createApplication({ job_id: job.id })
            addLocalApplicationSynced({
              job_id: job.id,
              job_title: job.title,
              school_name: job.school_name,
              recipient_email: job.apply_email,
              resume_name: this.data.selectedResume,
              template_name: this.data.selectedTemplate,
              status: "已确认"
            })
            wx.showToast({ title: "已确认", icon: "success" })
            setTimeout(() => wx.switchTab({ url: "/pages/applications/index" }), 500)
          } catch (error) {
            if (error && error.statusCode) {
              wx.showModal({
                title: "这次不能确认投递",
                content: error.message || "后端校验没有通过，请回公告原文核对后再处理。",
                showCancel: false
              })
              return
            }
            addLocalApplicationSynced({
              job_id: job.id,
              job_title: job.title,
              school_name: job.school_name,
              recipient_email: job.apply_email,
              resume_name: this.data.selectedResume,
              template_name: this.data.selectedTemplate,
              status: "待处理"
            })
            wx.showToast({ title: "已保存待处理", icon: "none" })
            setTimeout(() => wx.switchTab({ url: "/pages/applications/index" }), 500)
          } finally {
            wx.hideLoading()
          }
        }
      }
    })
  }
})
