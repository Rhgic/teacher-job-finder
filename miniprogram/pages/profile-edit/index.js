const { updateProfile } = require("../../utils/api")
const { getProfileDraft, saveProfileDraft, syncProfileDraftFromRemote } = require("../../utils/store")

Page({
  data: {
    form: {},
    sourceText: "本地",
    districtPresets: [
      { label: "全深圳", value: "罗湖区、福田区、南山区、盐田区、宝安区、龙岗区、龙华区、坪山区、光明区、大鹏新区、深汕特别合作区" },
      { label: "中心城区", value: "福田区、南山区、罗湖区" },
      { label: "通勤友好", value: "宝安区、龙华区、龙岗区、光明区" }
    ],
    subjectPresets: [
      { label: "音体美", value: "音乐、体育、美术" },
      { label: "主科", value: "语文、数学、英语" },
      { label: "理科", value: "物理、化学、生物、科学、信息技术" }
    ],
    stagePresets: [
      { label: "中小学", value: "小学、初中、高中" },
      { label: "小学初中", value: "小学、初中" },
      { label: "幼小", value: "幼儿园、小学" }
    ]
  },
  async onLoad() {
    this.setData({ form: getProfileDraft() })
    const result = await syncProfileDraftFromRemote()
    this.setData({ form: result.form, sourceText: result.source })
  },
  onInput(event) {
    const key = event.currentTarget.dataset.key
    this.setData({
      form: {
        ...this.data.form,
        [key]: event.detail.value
      }
    })
  },
  applyPreset(event) {
    const key = event.currentTarget.dataset.key
    const value = event.currentTarget.dataset.value
    this.setData({
      form: {
        ...this.data.form,
        [key]: value
      }
    })
  },
  async save() {
    saveProfileDraft(this.data.form)
    wx.setStorageSync("onboarding_profile_saved", "1")
    wx.showLoading({ title: "保存中" })
    try {
      await updateProfile(this.data.form)
      wx.showToast({ title: "已同步", icon: "success" })
    } catch (error) {
      wx.showToast({ title: "已本地保存", icon: "none" })
    } finally {
      wx.hideLoading()
      setTimeout(() => wx.navigateBack(), 500)
    }
  }
})
