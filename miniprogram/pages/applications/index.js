const { getApplications, updateApplicationStatus: updateRemoteApplicationStatus } = require("../../utils/api")
const {
  addLocalApplicationNoteSynced,
  getLocalApplications,
  syncLocalApplicationsFromRemote,
  updateLocalApplicationStatusSynced
} = require("../../utils/store")

const STATUS_OPTIONS = ["待处理", "已发送", "已面试", "已录用", "未通过"]
const REMOTE_STATUS_MAP = {
  "待处理": "pending",
  "已发送": "sent"
}

function normalizeStatus(status) {
  const map = {
    pending: "待发送",
    sent: "已发送",
    delivered: "已送达",
    failed: "发送失败",
    bounced: "已退信",
    "待处理": "待处理",
    "已确认": "已确认",
    "已面试": "已面试",
    "已录用": "已录用",
    "未通过": "未通过"
  }
  return map[status] || status || "待处理"
}

Page({
  data: {
    records: [],
    confirmedCount: 0,
    pendingCount: 0,
    isEmpty: false
  },
  onShow() {
    this.loadApplications()
  },
  async loadApplications() {
    const remote = await getApplications()
    const local = await syncLocalApplicationsFromRemote()
    const localRecords = local.map((item) => ({ ...item, isLocal: true }))
    const remoteRecords = (remote || []).map((item) => ({ ...item, isLocal: false }))
    const records = localRecords.concat(remoteRecords).map((item) => {
      const statusText = normalizeStatus(item.status)
      return {
        ...item,
        statusText,
        statusClass: ["发送失败", "已退信", "未通过"].includes(statusText)
          ? "warn"
          : ["已发送", "已送达", "已面试", "已录用"].includes(statusText)
            ? "green"
            : "gray"
      }
    })
    const confirmedCount = records.filter((item) => ["已确认", "已发送", "已送达", "已面试", "已录用"].includes(item.statusText)).length
    const pendingCount = records.filter((item) => ["待处理", "待发送"].includes(item.statusText)).length
    this.setData({
      records,
      confirmedCount,
      pendingCount,
      isEmpty: records.length === 0
    })
  },
  changeStatus(event) {
    const id = event.currentTarget.dataset.id
    wx.showActionSheet({
      itemList: STATUS_OPTIONS,
      success: async (res) => {
        const status = STATUS_OPTIONS[res.tapIndex]
        const record = this.data.records.find((item) => item.id === id)
        if (record && record.isLocal) {
          updateLocalApplicationStatusSynced(id, status)
        } else if (REMOTE_STATUS_MAP[status]) {
          await updateRemoteApplicationStatus(id, REMOTE_STATUS_MAP[status])
        } else {
          wx.showToast({ title: "该状态暂只支持本地记录", icon: "none" })
          return
        }
        this.loadApplications()
        wx.showToast({ title: "状态已更新", icon: "success" })
      }
    })
  },
  addNote(event) {
    const id = event.currentTarget.dataset.id
    const record = this.data.records.find((item) => item.id === id)
    if (!record) return
    if (!record.isLocal) {
      wx.showToast({ title: "远端记录暂不能加备注", icon: "none" })
      return
    }
    wx.showModal({
      title: "添加跟进记录",
      editable: true,
      placeholderText: "例如：已发邮件，周五再看回复",
      success: (res) => {
        if (!res.confirm || !res.content) return
        addLocalApplicationNoteSynced(id, res.content)
        this.loadApplications()
        wx.showToast({ title: "已记录", icon: "success" })
      }
    })
  }
})
