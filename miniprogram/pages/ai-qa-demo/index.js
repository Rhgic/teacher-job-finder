const DEMO_QUESTION = "这个岗位有编制吗？"
const API_BASE = "http://192.168.31.76:8000"

function normalizeSources(sources = []) {
  if (!Array.isArray(sources)) return []
  return sources.map((source, index) => ({
    id: `source-${index}`,
    title: source.title || "招聘公告",
    snippet: source.snippet || "暂无片段"
  }))
}

function askRag(question) {
  return new Promise((resolve, reject) => {
    wx.request({
      url: `${API_BASE}/rag/ask`,
      method: "POST",
      data: { question },
      header: { "Content-Type": "application/json" },
      timeout: 8000,
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data)
          return
        }
        reject(new Error(`HTTP ${res.statusCode}`))
      },
      fail: reject
    })
  })
}

Page({
  data: {
    question: "",
    answer: "",
    answerTitle: "回答",
    answerPillText: "有出处",
    answerPillClass: "green",
    sources: [],
    hasSources: false,
    loading: false,
    errorText: ""
  },

  onQuestionInput(event) {
    this.setData({ question: event.detail.value || "" })
  },

  runDemoQuestion() {
    this.setData({ question: DEMO_QUESTION })
    this.submitQuestion()
  },

  async submitQuestion() {
    const question = this.data.question.trim()
    if (!question) {
      wx.showToast({ title: "先输入一个问题", icon: "none" })
      return
    }
    if (this.data.loading) return

    this.setData({
      loading: true,
      answer: "",
      sources: [],
      hasSources: false,
      errorText: ""
    })
    wx.showLoading({ title: "正在查询公告" })

    try {
      const data = await askRag(question)
      const found = data && data.found === true
      const sources = found ? normalizeSources(data.sources) : []
      this.setData({
        answer: data && data.answer ? data.answer : "提供的公告未提及该信息，建议查看公告原文。",
        answerTitle: found ? "回答" : "公告未提及",
        answerPillText: found ? "有出处" : "需核对",
        answerPillClass: found ? "green" : "warn",
        sources,
        hasSources: sources.length > 0
      })
      wx.setStorageSync("onboarding_rag_tried", "1")
    } catch (error) {
      this.setData({ errorText: "查询失败，请稍后重试。" })
      wx.showToast({ title: "查询失败", icon: "none" })
    } finally {
      wx.hideLoading()
      this.setData({ loading: false })
    }
  }
})
