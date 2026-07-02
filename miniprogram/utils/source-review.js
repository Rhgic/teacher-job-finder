function getSourceHost(url) {
  const match = String(url || "").match(/^https?:\/\/([^/?#]+)/i)
  return match ? match[1].toLowerCase() : ""
}

function isOfficialSource(url) {
  const host = getSourceHost(url)
  if (!host) return false
  return (
    host.endsWith(".gov.cn") ||
    host.includes("sz.gov.cn") ||
    host.includes("edu.cn") ||
    host.includes("szeb") ||
    host.includes("school") ||
    host.includes("edu")
  )
}

function buildSourceReview(job = {}) {
  const sourceUrl = job.source_url || ""
  const sourceHost = getSourceHost(sourceUrl)
  const official = isOfficialSource(sourceUrl)
  const riskTips = []

  let sourceStatusText = "暂无来源"
  let sourceStatusClass = "gray"
  if (sourceUrl && official) {
    sourceStatusText = "官方来源"
    sourceStatusClass = "green"
  } else if (sourceUrl) {
    sourceStatusText = "来源待确认"
    sourceStatusClass = "warn"
  }

  if (!sourceUrl) {
    riskTips.push("缺少公告来源，投递前请回到招聘方官方渠道核对。")
  } else if (!official) {
    riskTips.push("来源不是明确官方域名，建议再核对学校官网或教育局公告。")
  }
  if (!job.apply_email) {
    riskTips.push("招聘邮箱未解析到，投递方式需要查看公告原文。")
  }
  if (!job.deadline_at) {
    riskTips.push("截止日期待确认，避免错过报名时间。")
  }
  if (!riskTips.length) {
    riskTips.push("来源、邮箱和截止日期已初步具备，投递前仍建议核对公告原文。")
  }

  return {
    sourceHost,
    sourceHostText: sourceHost || "暂无公告域名",
    sourceText: sourceUrl || "公告原文待补充",
    sourceStatusText,
    sourceStatusClass,
    emailRiskText: job.apply_email ? "招聘邮箱已解析" : "邮箱待确认",
    deadlineRiskText: job.deadline_at ? "截止日期明确" : "截止待确认",
    riskTips
  }
}

module.exports = {
  buildSourceReview,
  getSourceHost,
  isOfficialSource
}
