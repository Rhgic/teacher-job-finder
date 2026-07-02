const {
  addResumeSynced,
  deleteResumeSynced,
  getResumes,
  syncResumesFromRemote,
  uploadResumeSynced,
  updateResumeSynced
} = require("../../utils/store")
const { runPipeline } = require("../../utils/api")

function buildDraft() {
  return {
    id: "",
    name: "",
    summary: ""
  }
}

function buildHighlights(summary) {
  return String(summary || "")
    .split(/[、,，;；\n\s]+/)
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, 3)
}

Page({
  data: {
    resumes: [],
    sourceText: "本地",
    draft: buildDraft(),
    editingId: "",
    formTitle: "新增简历",
    submitText: "保存简历",
    isEditing: false
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
      summary: "基本信息、目标岗位、待补教学成果",
      completeness: 38,
      updated_at: "刚刚",
      highlights: ["基本信息", "目标岗位", "待补教学成果"],
      file_url: "local://resume-placeholder",
      is_default: false
    }
    const result = await addResumeSynced(resume)
    wx.setStorageSync("onboarding_resume_added", "1")
    wx.showToast({ title: result.synced ? "已同步" : "已本地保存", icon: result.synced ? "success" : "none" })
    this.load()
  },
  onDraftInput(event) {
    const key = event.currentTarget.dataset.key
    this.setData({
      draft: {
        ...this.data.draft,
        [key]: event.detail.value
      }
    })
  },
  async saveResume() {
    const name = String(this.data.draft.name || "").trim() || "教师简历"
    const summary = String(this.data.draft.summary || "").trim()
    if (!summary) {
      wx.showToast({ title: "先写简历摘要", icon: "none" })
      return
    }
    const resume = {
      id: this.data.editingId || `resume-${Date.now()}`,
      name,
      summary,
      completeness: 76,
      updated_at: "刚刚",
      highlights: buildHighlights(summary),
      file_url: "local://resume-placeholder",
      is_default: !this.data.editingId
    }
    wx.showLoading({ title: "保存中" })
    try {
      const result = this.data.editingId
        ? await updateResumeSynced(resume)
        : await addResumeSynced(resume)
      wx.setStorageSync("onboarding_resume_added", "1")
      wx.showToast({ title: result.synced ? "已同步" : "已本地保存", icon: result.synced ? "success" : "none" })
      this.resetForm()
      this.load()
    } finally {
      wx.hideLoading()
    }
  },
  editResume(event) {
    const id = event.currentTarget.dataset.id
    const resume = this.data.resumes.find((item) => item.id === id)
    if (!resume) return
    this.setData({
      draft: {
        id: resume.id,
        name: resume.name || "",
        summary: resume.summary || (resume.highlights || []).join("、")
      },
      editingId: resume.id,
      formTitle: "编辑简历",
      submitText: "保存修改",
      isEditing: true
    })
  },
  resetForm() {
    this.setData({
      draft: buildDraft(),
      editingId: "",
      formTitle: "新增简历",
      submitText: "保存简历",
      isEditing: false
    })
  },
  deleteResume(event) {
    const id = event.currentTarget.dataset.id
    const resume = this.data.resumes.find((item) => item.id === id)
    if (!resume) return
    wx.showModal({
      title: "删除简历",
      content: `确认删除「${resume.name}」吗？`,
      confirmText: "删除",
      confirmColor: "#b42318",
      success: async (res) => {
        if (!res.confirm) return
        wx.showLoading({ title: "删除中" })
        try {
          const result = await deleteResumeSynced(id)
          if (this.data.editingId === id) this.resetForm()
          wx.showToast({ title: result.synced ? "已删除" : "已本地删除", icon: "none" })
          this.load()
        } finally {
          wx.hideLoading()
        }
      }
    })
  },
  chooseResumeFile() {
    wx.chooseMessageFile({
      count: 1,
      type: "file",
      extension: ["pdf", "txt", "md", "doc", "docx"],
      success: async (res) => {
        const file = res.tempFiles && res.tempFiles[0]
        if (!file || !file.path) return
        wx.showLoading({ title: "上传解析中" })
        try {
          const name = String(file.name || "上传简历").replace(/\.[^.]+$/, "")
          const result = await uploadResumeSynced(file.path, name)
          wx.setStorageSync("onboarding_resume_added", "1")
          this.resetForm()
          await this.load()
          try {
            await runPipeline()
          } catch (error) {
            // 匹配失败不影响简历保存。
          }
          wx.showToast({ title: result.synced ? "已上传" : "已保存", icon: "success" })
        } catch (error) {
          wx.showModal({
            title: "上传失败",
            content: error && error.message ? error.message : "请换一个 PDF、Word 或 TXT 文件再试。",
            showCancel: false
          })
        } finally {
          wx.hideLoading()
        }
      },
      fail: () => {
        wx.showToast({ title: "未选择文件", icon: "none" })
      }
    })
  },
  showUploadTip() {
    wx.showModal({
      title: "上传说明",
      content: "支持 PDF、TXT、Markdown；Word 文件当前会保存文件，但自动解析能力有限。上传后会作为默认简历参与岗位匹配。",
      showCancel: false
    })
  }
})
