const { askRag } = require("../../utils/api")

const EXAMPLES = [
  "翠园东晓中学这个岗位有编制吗？",
  "南山区实验学校报名截止到什么时候？",
  "宝安中学集团体育教师薪资是多少？"
]

const DEMO_QUESTION = "翠园东晓中学这个岗位有编制吗？"

function normalizeSources(sources = []) {
  if (!Array.isArray(sources)) return []
  return sources.map((source, index) => ({
    id: `source-${index}`,
    title: source.title || "招聘公告",
    snippet: source.snippet || "暂无片段"
  }))
}

Page({
  data: {
    question: "",
    answer: "",
    found: null,
    sources: [],
    examples: EXAMPLES,
    demoQuestion: DEMO_QUESTION,
    loading: false,
    hasAsked: false,
    hasSources: false,
    answerTitle: "回答",
    answerPillText: "有出处",
    answerPillClass: "green",
    errorText: ""
  },

  onQuestionInput(event) {
    this.setData({ question: event.detail.value || "" })
  },

  useExample(event) {
    const text = event.currentTarget.dataset.text || ""
    this.setData({ question: text })
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
      hasAsked: true,
      answer: "",
      found: null,
      sources: [],
      hasSources: false,
      errorText: ""
    })
    wx.showLoading({ title: "正在查询公告" })

    try {
      const data = await askRag(question)
      const found = data && data.found === true
      this.setData({
        answer: data && data.answer ? data.answer : "提供的公告未提及该信息，建议查看公告原文。",
        found,
        sources: found ? normalizeSources(data.sources) : [],
        hasSources: found && Array.isArray(data.sources) && data.sources.length > 0,
        answerTitle: found ? "回答" : "公告未提及",
        answerPillText: found ? "有出处" : "需核对",
        answerPillClass: found ? "green" : "warn"
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
