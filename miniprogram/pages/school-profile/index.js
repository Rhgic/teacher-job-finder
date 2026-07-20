const { getJobs } = require("../../utils/api")
const { buildSourceReview } = require("../../utils/source-review")

function uniqueText(items) {
  const values = Array.from(new Set(items.filter(Boolean)))
  return values.length ? values.join("、") : "待确认"
}

function normalizeJob(job) {
  const review = buildSourceReview(job)
  return {
    ...job,
    sourceStatusText: review.sourceStatusText,
    sourceStatusClass: review.sourceStatusClass,
    deadlineText: job.deadline_at ? String(job.deadline_at).slice(0, 10) : "待定"
  }
}

Page({
  data: {
    schoolName: "学校画像",
    districtText: "深圳",
    stageText: "待确认",
    subjectText: "待确认",
    jobCount: 0,
    establishmentCount: 0,
    sourceReadyCount: 0,
    jobs: [],
    empty: false
  },
  async onLoad(options) {
    const name = decodeURIComponent(options.school || "")
    const jobs = (await getJobs()).filter((job) => job.school_name === name).map(normalizeJob)
    this.setData({
      schoolName: name || "学校画像",
      districtText: uniqueText(jobs.map((job) => job.district)),
      stageText: uniqueText(jobs.map((job) => job.stage)),
      subjectText: uniqueText(jobs.map((job) => job.subject)),
      jobCount: jobs.length,
      establishmentCount: jobs.filter((job) => job.is_establishment).length,
      sourceReadyCount: jobs.filter((job) => job.source_url).length,
      jobs,
      empty: jobs.length === 0
    })
  },
  openJob(event) {
    const id = event.currentTarget.dataset.id
    if (id) wx.navigateTo({ url: `/pages/job-detail/index?id=${id}` })
  }
})
