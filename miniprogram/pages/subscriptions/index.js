const { addSubscriptionSynced, getSubscriptions, saveSubscriptions, syncSubscriptionsFromRemote, updateSubscriptionSynced } = require("../../utils/store")

const RULE_PRESETS = [
  {
    name: "全深圳教师岗位",
    district: "全深圳",
    stage: "不限",
    subject: "不限",
    bianzhi: "不限"
  },
  {
    name: "音体美教师岗位",
    district: "全深圳",
    stage: "小学、初中、高中",
    subject: "音乐、体育、美术",
    bianzhi: "不限"
  },
  {
    name: "中心城区主科岗位",
    district: "福田区、南山区、罗湖区",
    stage: "小学、初中",
    subject: "语文、数学、英语",
    bianzhi: "优先编制"
  }
]

Page({
  data: {
    subscriptions: [],
    sourceText: "本地"
  },
  onShow() {
    this.load()
  },
  async load() {
    const result = await syncSubscriptionsFromRemote()
    this.setData({ subscriptions: result.list, sourceText: result.source })
  },
  async addRule() {
    const list = getSubscriptions()
    const preset = RULE_PRESETS[list.length % RULE_PRESETS.length]
    const rule = {
      id: `rule-${Date.now()}`,
      ...preset,
      enabled: true
    }
    const result = await addSubscriptionSynced(rule)
    wx.setStorageSync("onboarding_subscription_added", "1")
    wx.showToast({ title: result.synced ? "已同步" : "已本地添加", icon: result.synced ? "success" : "none" })
    this.load()
  },
  async toggleRule(event) {
    const id = event.currentTarget.dataset.id
    const base = this.data.subscriptions.length ? this.data.subscriptions : getSubscriptions()
    const list = base.map((item) => item.id === id ? { ...item, enabled: !item.enabled } : item)
    saveSubscriptions(list)
    const changed = list.find((item) => item.id === id)
    if (changed) await updateSubscriptionSynced(changed, list)
    this.load()
  }
})
