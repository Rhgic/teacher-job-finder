const { getReadiness } = require("../../utils/api")

const REQUIRED_LABELS = {
  wechat_appid: "微信 AppID",
  wechat_secret: "微信 AppSecret",
  session_secret: "会话密钥",
  admin_api_token: "后台管理令牌",
  auth_dev_mode_off: "关闭开发登录",
  jobs_available: "岗位数据"
}

const OPTIONAL_LABELS = {
  llm_real_mode: "真实 AI 匹配",
  mailer_real_mode: "真实邮件投递",
  cos_configured: "COS 简历存储"
}

function toItems(data = {}, labels = {}) {
  return Object.keys(labels).map((key) => ({
    key,
    label: labels[key],
    ok: data[key] === true,
    text: data[key] === true ? "已就绪" : "待配置"
  }))
}

function formatTime(value) {
  return value ? String(value).slice(0, 16).replace("T", " ") : "暂无"
}

function formatSize(bytes) {
  if (!bytes || Number(bytes) <= 0) return "暂无"
  const mb = Number(bytes) / 1024 / 1024
  if (mb >= 1) return `${mb.toFixed(1)} MB`
  return `${Math.max(1, Math.round(Number(bytes) / 1024))} KB`
}

Page({
  data: {
    loading: true,
    statusText: "检查中",
    statusClass: "gray",
    requiredItems: [],
    optionalItems: [],
    jobsCount: 0,
    activeRulesCount: 0,
    latestJobAt: "暂无",
    backupOk: false,
    backupCount: 0,
    backupLatestAt: "暂无",
    backupLatestSize: "暂无",
    backupLatestFile: "暂无",
    nextStep: "正在读取服务器状态"
  },
  onShow() {
    this.load()
  },
  async load() {
    this.setData({ loading: true })
    try {
      const data = await getReadiness()
      const requiredItems = toItems(data.required, REQUIRED_LABELS)
      const optionalItems = toItems(data.optional, OPTIONAL_LABELS)
      const backup = data.backup || {}
      const missing = requiredItems.filter((item) => !item.ok).map((item) => item.label)
      this.setData({
        loading: false,
        statusText: data.status === "ok" ? "可提交前检查" : "还差配置",
        statusClass: data.status === "ok" ? "green" : "warn",
        requiredItems,
        optionalItems,
        jobsCount: data.counts && data.counts.jobs ? data.counts.jobs : 0,
        activeRulesCount: data.counts && data.counts.active_rules ? data.counts.active_rules : 0,
        latestJobAt: formatTime(data.latest_job_at),
        backupOk: backup.ok === true,
        backupCount: backup.count || 0,
        backupLatestAt: formatTime(backup.latest_at),
        backupLatestSize: formatSize(backup.latest_size_bytes),
        backupLatestFile: backup.latest_file || "暂无",
        nextStep: missing.length ? `还差：${missing.join("、")}` : "后端必填项已就绪，可以继续 HTTPS 域名和微信审核。"
      })
    } catch (error) {
      this.setData({
        loading: false,
        statusText: "读取失败",
        statusClass: "gray",
        nextStep: "请确认后端服务和本地隧道是否正常。"
      })
    }
  }
})
