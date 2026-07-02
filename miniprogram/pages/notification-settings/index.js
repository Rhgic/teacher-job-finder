const {
  getNotificationPreferences,
  saveNotificationPreferencesSynced,
  syncNotificationPreferencesFromRemote
} = require("../../utils/store")

const DAY_OPTIONS = [1, 2, 3, 5, 7]
const TEMPLATE_KEYS = ["deadline", "application", "materials", "daily"]

function enabledTemplateIds(prefs) {
  const templates = getApp().globalData.subscribeTemplates || {}
  return TEMPLATE_KEYS
    .filter((key) => prefs[key] !== false)
    .map((key) => templates[key])
    .filter(Boolean)
}

Page({
  data: {
    prefs: {},
    sourceText: "本地",
    authText: "未授权",
    dayOptions: DAY_OPTIONS,
    dayIndex: 2
  },
  async onShow() {
    const local = getNotificationPreferences()
    this.render(local, "本地")
    const result = await syncNotificationPreferencesFromRemote()
    this.render(result.value, result.source)
  },
  render(prefs, sourceText) {
    const dayIndex = Math.max(0, DAY_OPTIONS.indexOf(Number(prefs.days_before || 3)))
    this.setData({ prefs, sourceText, dayIndex })
  },
  requestSubscribe() {
    const tmplIds = enabledTemplateIds(this.data.prefs)
    if (!tmplIds.length) {
      wx.showModal({
        title: "还差一个微信模板",
        content: "现在偏好已经能保存，但微信订阅消息模板 ID 还没配置。等你在微信后台申请模板后，把模板 ID 填进配置，就能弹出授权。",
        showCancel: false
      })
      return
    }
    wx.requestSubscribeMessage({
      tmplIds,
      success: (res) => {
        const accepted = tmplIds.filter((id) => res[id] === "accept").length
        this.setData({ authText: accepted > 0 ? `已授权 ${accepted} 类` : "未授权" })
        wx.showToast({ title: accepted > 0 ? "已授权" : "未授权", icon: accepted > 0 ? "success" : "none" })
      },
      fail: () => {
        wx.showToast({ title: "授权失败，请稍后再试", icon: "none" })
      }
    })
  },
  async toggle(event) {
    const key = event.currentTarget.dataset.key
    const prefs = { ...this.data.prefs, [key]: !this.data.prefs[key] }
    await this.save(prefs)
  },
  async onDayChange(event) {
    const index = Number(event.detail.value || 0)
    const prefs = { ...this.data.prefs, days_before: DAY_OPTIONS[index] }
    await this.save(prefs)
  },
  onTimeInput(event) {
    const key = event.currentTarget.dataset.key
    this.setData({
      prefs: {
        ...this.data.prefs,
        [key]: event.detail.value
      }
    })
  },
  async saveTimes() {
    await this.save(this.data.prefs)
  },
  async save(prefs) {
    this.render(prefs, this.data.sourceText)
    const result = await saveNotificationPreferencesSynced(prefs)
    this.setData({ sourceText: result.synced ? "云端" : "本地" })
    wx.showToast({ title: result.synced ? "已同步" : "已本地保存", icon: result.synced ? "success" : "none" })
  }
})
