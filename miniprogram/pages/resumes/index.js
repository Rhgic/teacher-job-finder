const { addResumeSynced, getResumes, syncResumesFromRemote } = require("../../utils/store")

Page({
  data: {
    resumes: [],
    sourceText: "本地"
  },
  onShow() {
    this.load()
  },
  async load() {
    const result = await syncResumesFromRemote()
    this.setData({ resumes: result.list, sourceText: result.source })
  },
  async addDemoResume() {
    const list = getResumes()
    const resume = {
      id: `resume-${Date.now()}`,
      name: `教师简历 ${list.length + 1}`,
      completeness: 38,
      updated_at: "刚刚",
      highlights: ["基本信息", "目标岗位", "待补教学成果"]
    }
    const result = await addResumeSynced(resume)
    wx.setStorageSync("onboarding_resume_added", "1")
    wx.showToast({ title: result.synced ? "已同步" : "已本地保存", icon: result.synced ? "success" : "none" })
    this.load()
  },
  showUploadTip() {
    wx.showModal({
      title: "上传简历",
      content: "正式版会支持上传 PDF/Word，并解析成结构化简历。当前先保留入口和简历管理流程。",
      showCancel: false
    })
  }
})
