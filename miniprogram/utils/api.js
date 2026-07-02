const fallbackJobs = [
  { id: "demo-001", title: "南山区实验学校小学语文教师招聘", school_name: "南山区实验学校", district: "南山区", stage: "小学", subject: "语文", salary_min: 15000, salary_max: 23000, recruiter_email: "hr1@example.edu.cn", is_establishment: true, description: "班主任经验优先，普通话二甲及以上。" },
  { id: "demo-002", title: "宝安中学集团高中体育教师招聘", school_name: "宝安中学集团", district: "宝安区", stage: "高中", subject: "体育", salary_min: 17000, salary_max: 27000, recruiter_email: "hr2@example.edu.cn", is_establishment: true, description: "足球或田径专项，能组织校队训练。" },
  { id: "demo-003", title: "龙岗外国语学校初中英语教师招聘", school_name: "龙岗外国语学校", district: "龙岗区", stage: "初中", subject: "英语", salary_min: 15000, salary_max: 24000, recruiter_email: "", is_establishment: false, description: "口语表达优秀，有班主任经历优先。" }
]

const fallbackProfile = {
  real_name: "王老师",
  email: "teacher@example.com",
  target_districts: ["南山区", "宝安区"],
  target_stages: ["小学", "初中", "高中"],
  target_subjects: ["体育", "语文"]
}

function baseUrl() {
  return getApp().globalData.apiBase
}

function request(path, options = {}) {
  return new Promise((resolve, reject) => {
    const token = wx.getStorageSync("auth_token")
    const header = Object.assign({}, options.header || {})
    if (token) {
      header.Authorization = `Bearer ${token}`
    }
    wx.request({
      url: `${baseUrl()}${path}`,
      method: options.method || "GET",
      data: options.data || {},
      header,
      timeout: 8000,
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data)
        } else {
          const message = res.data && (res.data.detail || res.data.message)
          const error = new Error(typeof message === "string" ? message : `HTTP ${res.statusCode}`)
          error.statusCode = res.statusCode
          error.response = res.data
          reject(error)
        }
      },
      fail: reject
    })
  })
}

function wxLogin() {
  return new Promise((resolve, reject) => {
    wx.login({
      success(result) {
        if (result.code) {
          resolve(result.code)
        } else {
          reject(new Error("微信没有返回登录 code"))
        }
      },
      fail: reject
    })
  })
}

async function loginWithWechat() {
  const code = await wxLogin()
  const data = await request("/auth/login", {
    method: "POST",
    data: { code }
  })
  if (!data || !data.token) {
    throw new Error("后端没有返回登录态")
  }
  wx.setStorageSync("auth_token", data.token)
  wx.setStorageSync("user_id", data.user_id || "")
  return data
}

function logout() {
  wx.removeStorageSync("auth_token")
  wx.removeStorageSync("user_id")
}

function getAuthState() {
  return {
    token: wx.getStorageSync("auth_token") || "",
    userId: wx.getStorageSync("user_id") || ""
  }
}

function buildQuery(params = {}) {
  return Object.keys(params)
    .filter((key) => params[key] !== undefined && params[key] !== null && params[key] !== "")
    .map((key) => `${key}=${encodeURIComponent(params[key])}`)
    .join("&")
}

function buildJobTitle(job = {}) {
  const school = (job.school_name || "").trim()
  const stage = (job.stage || "").trim()
  const subject = (job.subject || "").trim()
  const parts = []
  if (school) parts.push(school)
  // 学校名已含学段（如“…小学”“…中学”）时不再重复学段，避免“小学小学”这类拼接错误
  if (stage && !school.endsWith(stage)) parts.push(stage)
  if (subject) parts.push(subject)
  const body = parts.join("") || "教师"
  return `${body}招聘`
}

function normalizeJob(job = {}) {
  const title = job.title || buildJobTitle(job)
  const sourceUrl = job.source_url || ""
  const isEstablishment = job.is_establishment !== undefined
    ? Boolean(job.is_establishment)
    : Boolean(job.has_bianzhi)
  const deadline = job.deadline || job.deadline_at || ""
  const recruiterEmail = job.recruiter_email || job.apply_email || ""
  return {
    ...job,
    title,
    jd: job.description || job.jd || "请查看公告原文核对岗位要求。",
    description: job.description || job.jd || "",
    is_establishment: isEstablishment,
    has_bianzhi: isEstablishment,
    recruiter_email: recruiterEmail,
    apply_email: recruiterEmail,
    deadline,
    deadline_at: deadline,
    source_url: sourceUrl,
    headcount: job.headcount || 1
  }
}

async function getJobs(params = {}) {
  try {
    const query = buildQuery({ page_size: 100, ...params })
    const data = await request(`/jobs${query ? `?${query}` : ""}`)
    const rawJobs = Array.isArray(data) ? data : Array.isArray(data && data.items) ? data.items : []
    const jobs = rawJobs.map(normalizeJob)
    wx.setStorageSync("jobs", jobs)
    return jobs
  } catch (error) {
    return wx.getStorageSync("jobs") || fallbackJobs.map(normalizeJob)
  }
}

async function getJob(id) {
  try {
    const data = await request(`/jobs/${id}`)
    return normalizeJob(data)
  } catch (error) {
    const jobs = wx.getStorageSync("jobs") || fallbackJobs.map(normalizeJob)
    return jobs.find((job) => job.id === id) || jobs[0] || {}
  }
}

async function getProfile() {
  try {
    const profile = await request("/profile")
    const intent = profile.intent || {}
    return {
      ...profile,
      target_districts: profile.target_districts || intent.districts || [],
      target_stages: profile.target_stages || intent.stages || [],
      target_subjects: profile.target_subjects || intent.subjects || []
    }
  } catch (error) {
    return fallbackProfile
  }
}

async function updateProfile(profile) {
  const body = {
    real_name: profile.real_name || profile.name || undefined,
    email: profile.email || undefined,
    target_districts: splitText(profile.districts),
    target_stages: splitText(profile.stages),
    target_subjects: splitText(profile.subjects),
    intro: [
      profile.education ? `学历:${profile.education}` : "",
      profile.major ? `专业:${profile.major}` : "",
      profile.certificate ? `证书:${profile.certificate}` : "",
      profile.years ? `经验:${profile.years}` : "",
      profile.schoolType ? `学校偏好:${profile.schoolType}` : ""
    ].filter(Boolean).join(";")
  }
  return request("/profile", { method: "PUT", data: body })
}

function splitText(value) {
  if (Array.isArray(value)) return value
  return String(value || "")
    .split(/[、,，\\s]+/)
    .map((item) => item.trim())
    .filter(Boolean)
}

async function getRemoteResumes() {
  const data = await request("/resumes")
  return Array.isArray(data) ? data : []
}

async function createRemoteResume(resume) {
  return request("/resumes", {
    method: "POST",
    data: {
      name: resume.file_name || resume.name || "教师简历",
      file_url: resume.file_url || "local://resume-placeholder",
      summary: (resume.highlights || []).join("、") || resume.summary || "小程序演示简历",
      is_default: Boolean(resume.is_default)
    }
  })
}

async function uploadRemoteResume(filePath, name = "") {
  return new Promise((resolve, reject) => {
    const token = wx.getStorageSync("auth_token")
    const header = {}
    if (token) header.Authorization = `Bearer ${token}`
    wx.uploadFile({
      url: `${baseUrl()}/resumes/upload`,
      filePath,
      name: "file",
      formData: {
        name,
        user_openid: "demo-openid",
        is_default: "true"
      },
      header,
      timeout: 20000,
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          try {
            resolve(JSON.parse(res.data || "{}"))
          } catch (error) {
            reject(new Error("后端返回格式不是 JSON"))
          }
          return
        }
        let detail = `HTTP ${res.statusCode}`
        try {
          const data = JSON.parse(res.data || "{}")
          detail = data.detail || detail
        } catch (error) {
          // 保留默认错误。
        }
        reject(new Error(detail))
      },
      fail: reject
    })
  })
}

async function updateRemoteResume(resume) {
  return request(`/resumes/${resume.id}`, {
    method: "PUT",
    data: {
      name: resume.file_name || resume.name || "教师简历",
      file_url: resume.file_url || "local://resume-placeholder",
      summary: (resume.highlights || []).join("、") || resume.summary || "小程序演示简历",
      is_default: Boolean(resume.is_default)
    }
  })
}

async function deleteRemoteResume(id) {
  return request(`/resumes/${id}`, { method: "DELETE" })
}

async function getRemoteRules() {
  const data = await request("/rules")
  return Array.isArray(data) ? data : []
}

async function createRemoteRule(rule) {
  return request("/rules", {
    method: "POST",
    data: {
      name: rule.name,
      districts: splitText(rule.district === "全深圳" ? "" : rule.district),
      stages: splitText(rule.stage === "不限" ? "" : rule.stage),
      subjects: splitText(rule.subject === "不限" ? "" : rule.subject),
      require_bianzhi: rule.bianzhi === "优先编制",
      active: rule.enabled !== false,
      threshold: 70
    }
  })
}

async function updateRemoteRule(rule) {
  return request(`/rules/${rule.id}`, {
    method: "PUT",
    data: {
      name: rule.name,
      districts: splitText(rule.district === "全深圳" ? "" : rule.district),
      stages: splitText(rule.stage === "不限" ? "" : rule.stage),
      subjects: splitText(rule.subject === "不限" ? "" : rule.subject),
      require_bianzhi: rule.bianzhi === "优先编制",
      active: rule.enabled !== false,
      threshold: 70
    }
  })
}

async function getMatches() {
  try {
    const data = await request("/recommendations")
    return (Array.isArray(data) ? data : []).map((match) => ({
      ...match,
      reason: match.match_reason || "岗位与订阅规则匹配",
      job: match.job ? normalizeJob(match.job) : null
    }))
  } catch (error) {
    const jobs = wx.getStorageSync("jobs") || fallbackJobs.map(normalizeJob)
    return jobs
      .filter((job) => job.subject === "体育" || job.district === "南山区")
      .map((job, index) => ({
        id: `fallback-match-${index}`,
        job_id: job.id,
        llm_score: job.subject === "体育" ? 88 : 78,
        reason: job.subject === "体育" ? "学科与求职方向高度匹配" : "区域与目标范围匹配",
        matched_points: [job.district, job.stage, job.subject],
        gaps: ["请查看公告原文核对附件要求"],
        cover_letter: `尊敬的${job.school_name}招聘负责人:您好!我希望应聘贵校${job.subject}教师岗位。`,
        job
      }))
  }
}

async function runPipeline() {
  return request("/pipeline/run", { method: "POST" })
}

async function runCrawl(maxDetailPages = 12, source = "all") {
  const query = buildQuery({
    source,
    max_detail_pages: maxDetailPages
  })
  return request(`/crawl/run?${query}`, { method: "POST" })
}

async function createApplication(data) {
  return request("/applications", { method: "POST", data })
}

async function getApplications() {
  try {
    return await request("/applications")
  } catch (error) {
    return []
  }
}

async function updateApplicationStatus(id, status) {
  return request(`/applications/${id}/status`, {
    method: "PATCH",
    data: { status }
  })
}

async function getRemoteSetting(key) {
  const data = await request(`/settings/${key}`)
  return data ? data.value : null
}

async function putRemoteSetting(key, value) {
  const data = await request(`/settings/${key}`, {
    method: "PUT",
    data: { value }
  })
  return data ? data.value : value
}

async function getReadiness() {
  return request("/readiness")
}

async function askRag(question) {
  return request("/rag/ask", {
    method: "POST",
    data: { question }
  })
}

module.exports = {
  fallbackJobs,
  askRag,
  buildJobTitle,
  getJobs,
  getJob,
  getProfile,
  getMatches,
  getApplications,
  getRemoteResumes,
  getRemoteRules,
  getRemoteSetting,
  getReadiness,
  deleteRemoteResume,
  uploadRemoteResume,
  createApplication,
  createRemoteResume,
  createRemoteRule,
  getAuthState,
  loginWithWechat,
  logout,
  request,
  runPipeline,
  runCrawl,
  putRemoteSetting,
  updateApplicationStatus,
  updateProfile,
  updateRemoteResume,
  updateRemoteRule
}
