const { askRag, getRagStatus } = require("../../utils/api")

const HISTORY_KEY = "rag_chat_history_v2"
const MAX_HISTORY = 8

const EXAMPLES = [
  { short: "编", label: "核对编制", text: "翠园东晓中学这个岗位有编制吗？", tone: "green" },
  { short: "期", label: "查询截止时间", text: "南山区实验学校报名截止到什么时候？", tone: "blue" },
  { short: "薪", label: "查看薪资范围", text: "宝安中学集团体育教师薪资是多少？", tone: "amber" }
]

const FOLLOW_UPS = ["那截止到什么时候？", "薪资是多少？", "投递邮箱是什么？"]

function normalizeSources(sources = []) {
  if (!Array.isArray(sources)) return []
  return sources.map((source, index) => {
    const score = Number(source.score || 0)
    const sourceId = source.source_id || source.sourceId || ""
    return {
      id: sourceId || `source-${index}`,
      sourceId,
      title: source.title || "招聘公告",
      snippet: source.snippet || "暂无公告片段",
      scoreText: source.scoreText || (score > 0 ? `相似度 ${Math.round(Math.min(score, 1) * 100)}%` : "")
    }
  })
}

function createMessage(question) {
  return {
    id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    question,
    answer: "",
    found: false,
    sources: [],
    sourcesExpanded: false,
    loading: true,
    error: ""
  }
}

function restoredMessages() {
  const stored = wx.getStorageSync(HISTORY_KEY)
  if (!Array.isArray(stored)) return []
  return stored.slice(-MAX_HISTORY).map((message) => ({
    ...message,
    loading: false,
    error: "",
    sourcesExpanded: false,
    sources: normalizeSources(message.sources)
  }))
}

Page({
  data: {
    question: "",
    canSubmit: false,
    questionFocused: false,
    messages: [],
    examples: EXAMPLES,
    followUps: FOLLOW_UPS,
    loading: false,
    lastContextTitle: "",
    knowledgeStatus: "正在连接公告知识库",
    modeText: "",
    statusClass: ""
  },

  onLoad() {
    const messages = restoredMessages()
    const lastFound = [...messages].reverse().find((message) => message.found && message.sources.length)
    this.setData({
      messages,
      lastContextTitle: lastFound ? lastFound.sources[0].title : ""
    })
    this.loadKnowledgeStatus()
  },

  onShow() {
    this.loadKnowledgeStatus()
  },

  async loadKnowledgeStatus() {
    try {
      const status = await getRagStatus()
      this.setData({
        knowledgeStatus: status.ready
          ? `知识库已就绪 · ${status.jobs || 0} 个岗位 · ${status.chunks || 0} 个片段`
          : "知识库还没有建立索引",
        modeText: status.demo_mode ? "本地测试数据" : "在线知识库",
        statusClass: status.ready ? "" : "offline"
      })
    } catch (error) {
      this.setData({
        knowledgeStatus: "公告知识库暂时无法连接",
        modeText: "",
        statusClass: "offline"
      })
    }
  },

  onQuestionInput(event) {
    const question = event.detail.value || ""
    this.setData({ question, canSubmit: Boolean(question.trim()) })
  },

  onQuestionFocus() {
    this.setData({ questionFocused: true })
  },

  onQuestionBlur() {
    this.setData({ questionFocused: false })
  },

  useExample(event) {
    const question = event.currentTarget.dataset.text || ""
    if (!question || this.data.loading) return
    this.setData({ question, canSubmit: true })
    this.askQuestion(question)
  },

  submitQuestion() {
    const question = this.data.question.trim()
    if (!question) {
      wx.showToast({ title: "先输入一个问题", icon: "none" })
      return
    }
    this.askQuestion(question)
  },

  async askQuestion(question) {
    if (this.data.loading) return

    const message = createMessage(question)
    const messages = [...this.data.messages, message].slice(-MAX_HISTORY)
    const messageIndex = messages.length - 1
    const contextTitle = this.data.lastContextTitle
    this.setData({
      messages,
      question: "",
      canSubmit: false,
      loading: true
    })
    this.scrollToLatest()

    try {
      const data = await askRag(question, { topK: 3, contextTitle })
      const found = data && data.found === true
      const sources = found ? normalizeSources(data.sources) : []
      const updated = [...this.data.messages]
      updated[messageIndex] = {
        ...updated[messageIndex],
        answer: data && data.answer
          ? data.answer
          : "提供的公告未提及该信息，建议查看公告原文。",
        found,
        sources,
        sourcesExpanded: found && sources.length === 1,
        loading: false,
        error: ""
      }
      this.setData({
        messages: updated,
        lastContextTitle: found && sources.length ? sources[0].title : contextTitle
      })
      this.scrollToLatest()
      this.saveHistory()
      wx.setStorageSync("onboarding_rag_tried", "1")
    } catch (error) {
      const updated = [...this.data.messages]
      updated[messageIndex] = {
        ...updated[messageIndex],
        loading: false,
        error: "请确认后端已启动，并且手机和电脑连接的是同一个网络。"
      }
      this.setData({ messages: updated })
    } finally {
      this.setData({ loading: false })
    }
  },

  retryMessage(event) {
    if (this.data.loading) return
    const index = Number(event.currentTarget.dataset.index)
    const target = this.data.messages[index]
    if (!target) return
    const messages = this.data.messages.filter((_, itemIndex) => itemIndex !== index)
    this.setData({ messages })
    this.askQuestion(target.question)
  },

  toggleSources(event) {
    const index = Number(event.currentTarget.dataset.index)
    const messages = [...this.data.messages]
    if (!messages[index]) return
    messages[index] = {
      ...messages[index],
      sourcesExpanded: !messages[index].sourcesExpanded
    }
    this.setData({ messages })
  },

  copyAnswer(event) {
    const index = Number(event.currentTarget.dataset.index)
    const message = this.data.messages[index]
    if (!message || !message.answer) return
    wx.setClipboardData({ data: message.answer })
  },

  openSource(event) {
    const id = event.currentTarget.dataset.id || ""
    if (!id) {
      wx.showToast({ title: "这个片段没有关联岗位", icon: "none" })
      return
    }
    wx.navigateTo({ url: `/pages/job-detail/index?id=${encodeURIComponent(id)}` })
  },

  clearConversation() {
    wx.showModal({
      title: "清空问答记录",
      content: "只会清除这台设备上的本地记录。",
      confirmText: "清空",
      confirmColor: "#b54735",
      success: (result) => {
        if (!result.confirm) return
        wx.removeStorageSync(HISTORY_KEY)
        this.setData({ messages: [], lastContextTitle: "" })
      }
    })
  },

  saveHistory() {
    const messages = this.data.messages
      .filter((message) => !message.loading && !message.error)
      .slice(-MAX_HISTORY)
    wx.setStorageSync(HISTORY_KEY, messages)
  },

  scrollToLatest() {
    setTimeout(() => {
      wx.pageScrollTo({ scrollTop: 99999, duration: 180 })
    }, 40)
  }
})
