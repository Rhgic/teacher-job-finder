const { askRag } = require("../../utils/api")

const EXAMPLES = [
  "报名需要哪些材料？",
  "这个岗位有编制吗？",
  "截止到几号？"
]

function normalizeSources(sources = []) {
  if (!Array.isArray(sources)) return []
  return sources.map((source, index) => ({
    id: `source-${index}`,
    title: source.title || "招聘公告",
    snippet: source.snippet || "暂无片段",
    expanded: index === 0
  }))
}

Page({
  data: {
    question: "",
    answer: "",
    found: null,
    sources: [],
    examples: EXAMPLES,
    loading: false,
    hasAsked: false,
    errorText: ""
  },

  onQuestionInput(event) {
    this.setData({ question: event.detail.value || "" })
  },

  useExample(event) {
    const text = event.currentTarget.dataset.text || ""
    this.setData({ question: text })
  },

  toggleSource(event) {
    const id = event.currentTarget.dataset.id
    const sources = this.data.sources.map((source) => ({
      ...source,
      expanded: source.id === id ? !source.expanded : source.expanded
    }))
    this.setData({ sources })
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
      hasAsked: true,
      answer: "",
      found: null,
      sources: [],
      errorText: ""
    })
    wx.showLoading({ title: "正在查询公告" })

    try {
      const data = await askRag(question)
      const found = data && data.found === true
      this.setData({
        answer: data && data.answer ? data.answer : "提供的公告未提及该信息，建议查看公告原文。",
        found,
        sources: found ? normalizeSources(data.sources) : []
      })
      wx.setStorageSync("onboarding_rag_tried", "1")
    } catch (error) {
      this.setData({ errorText: "查询失败，请稍后重试。" })
      wx.showToast({ title: "查询失败，请稍后重试", icon: "none" })
    } finally {
      wx.hideLoading()
      this.setData({ loading: false })
    }
  }
})
