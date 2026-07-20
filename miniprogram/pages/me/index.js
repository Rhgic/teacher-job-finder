const { getAuthState, getProfile, loginWithWechat, logout } = require("../../utils/api")
const { getSubscriptions, syncResumesFromRemote } = require("../../utils/store")
const config = require("../../utils/config")

const ONBOARDING_STORAGE_KEY = "onboarding_hidden"
const ONBOARDING_PROFILE_KEY = "onboarding_profile_saved"
const ONBOARDING_RESUME_KEY = "onboarding_resume_added"
const ONBOARDING_SUBSCRIPTION_KEY = "onboarding_subscription_added"
const ONBOARDING_RAG_KEY = "onboarding_rag_tried"

function hasUserResume(resumes = []) {
  return wx.getStorageSync(ONBOARDING_RESUME_KEY) === "1" || resumes.some((item) => item.id !== "resume-default")
}

function hasUserSubscription(subscriptions = []) {
  return wx.getStorageSync(ONBOARDING_SUBSCRIPTION_KEY) === "1" || subscriptions.some((item) => !String(item.id || "").startsWith("default-"))
}

Page({
  data: {
    profile: {},
    // 仅开发环境显示“服务器状态”等调试入口；提审/正式发布(prod)自动隐藏
    isDev: config.ENV !== "prod",
    isLoggedIn: false,
    loginLoading: false,
    nameText: "演示用户",
    emailText: "未填写邮箱",
    districts: "全深圳",
    stages: "不限",
    subjects: "不限",
    readyScore: 0,
    readyItems: [],
    onboardingHidden: false,
    onboardingProgress: 0,
    onboardingTotal: 4,
    onboardingProgressPercent: 0,
    onboardingNextText: "先完善求职档案",
    onboardingNextUrl: "/pages/profile-edit/index",
    onboardingItems: []
  },
  onShow() {
    this.setData({ onboardingHidden: wx.getStorageSync(ONBOARDING_STORAGE_KEY) === "1" })
    this.syncAuthState()
    this.loadProfile()
  },
  syncAuthState() {
    const auth = getAuthState()
    this.setData({
      isLoggedIn: Boolean(auth.token)
    })
  },
  async loadProfile() {
    const profile = await getProfile()
    const auth = getAuthState()
    const resumeResult = await syncResumesFromRemote()
    const resumes = resumeResult.list || []
    const subscriptions = getSubscriptions().filter((item) => item.enabled !== false)
    const targetSubjects = profile.target_subjects || []
    const hasIntent = targetSubjects.length > 0 || (profile.target_districts || []).length > 0 || (profile.target_stages || []).length > 0
    const hasProfileSaved = wx.getStorageSync(ONBOARDING_PROFILE_KEY) === "1" || (auth.token && hasIntent)
    const hasResume = hasUserResume(resumes)
    const hasSubscription = hasUserSubscription(subscriptions)
    const readyItems = [
      {
        label: "微信登录",
        done: Boolean(auth.token),
        text: auth.token ? "已绑定" : "待绑定"
      },
      {
        label: "求职邮箱",
        done: Boolean(profile.email),
        text: profile.email ? "已填写" : "待填写"
      },
      {
        label: "目标学科",
        done: targetSubjects.length > 0,
        text: targetSubjects.length ? targetSubjects.join("、") : "待选择"
      },
      {
        label: "简历材料",
        done: resumes.length > 0,
        text: resumes.length ? `${resumes.length} 份` : "待添加"
      },
      {
        label: "岗位订阅",
        done: subscriptions.length > 0,
        text: subscriptions.length ? `${subscriptions.length} 条` : "待添加"
      }
    ]
    const readyScore = Math.round((readyItems.filter((item) => item.done).length / readyItems.length) * 100)
    const onboardingItems = [
      {
        label: "完善求职档案",
        desc: "告诉系统你想看哪些区域、学段和学科",
        done: hasProfileSaved,
        url: "/pages/profile-edit/index"
      },
      {
        label: "整理简历材料",
        desc: "先把简历、证书和常用附件放到一处",
        done: hasResume,
        url: "/pages/resumes/index"
      },
      {
        label: "创建岗位订阅",
        desc: "让新机会按你的目标自动提醒",
        done: hasSubscription,
        url: "/pages/subscriptions/index"
      },
      {
        label: "试一次公告问答",
        desc: "用公告问答核对材料、编制和截止时间",
        done: wx.getStorageSync(ONBOARDING_RAG_KEY) === "1",
        url: "/pages/rag-ask/index"
      }
    ]
    const onboardingProgress = onboardingItems.filter((item) => item.done).length
    const onboardingTotal = onboardingItems.length
    const nextItem = onboardingItems.find((item) => !item.done) || onboardingItems[onboardingItems.length - 1]
    this.setData({
      profile,
      nameText: profile.real_name || "演示用户",
      emailText: profile.email || "未填写邮箱",
      districts: (profile.target_districts || []).join("、") || "全深圳",
      stages: (profile.target_stages || []).join("、") || "不限",
      subjects: targetSubjects.join("、") || "不限",
      readyScore,
      readyItems,
      onboardingItems,
      onboardingProgress,
      onboardingTotal,
      onboardingProgressPercent: Math.round((onboardingProgress / onboardingTotal) * 100),
      onboardingNextText: nextItem.done ? "重新查看公告问答" : nextItem.label,
      onboardingNextUrl: nextItem.url
    })
  },
  async handleWechatLogin() {
    if (this.data.loginLoading) return
    this.setData({ loginLoading: true })
    wx.showLoading({ title: "登录中" })
    try {
      await loginWithWechat()
      this.syncAuthState()
      await this.loadProfile()
      wx.showToast({ title: "已登录", icon: "success" })
    } catch (error) {
      wx.showModal({
        title: "登录暂未完成",
        content: "页面流程已经接好，但后端需要配置微信 AppSecret 后才能换取真实登录态。现在仍可用演示模式继续体验。",
        showCancel: false
      })
    } finally {
      wx.hideLoading()
      this.setData({ loginLoading: false })
    }
  },
  handleLogout() {
    logout()
    this.syncAuthState()
    wx.showToast({ title: "已退出", icon: "none" })
  },
  openFeature(event) {
    const url = event.currentTarget.dataset.url
    if (url) wx.navigateTo({ url })
  },
  openOnboardingNext() {
    if (this.data.onboardingNextUrl) {
      wx.navigateTo({ url: this.data.onboardingNextUrl })
    }
  },
  openOnboardingStep(event) {
    const url = event.currentTarget.dataset.url
    if (url) wx.navigateTo({ url })
  },
  hideOnboarding() {
    wx.setStorageSync(ONBOARDING_STORAGE_KEY, "1")
    this.setData({ onboardingHidden: true })
  },
  showUploadTip() {
    wx.showModal({
      title: "简历上传",
      content: "生产环境会接腾讯云 COS。当前演示版先保留入口，不上传真实文件。",
      showCancel: false
    })
  }
})
