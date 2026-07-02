const FAVORITES_KEY = "favorite_jobs"
const SUBSCRIPTIONS_KEY = "job_subscriptions"
const RESUMES_KEY = "resume_profiles"
const PROFILE_DRAFT_KEY = "profile_draft"
const LOCAL_APPLICATIONS_KEY = "local_applications"
const MATERIALS_KEY = "job_materials_checklist"
const SAVED_SEARCHES_KEY = "saved_job_searches"
const NOTIFICATION_PREFS_KEY = "notification_preferences"

let apiModule = null

function api() {
  if (!apiModule) {
    apiModule = require("./api")
  }
  return apiModule
}

function read(key, fallback) {
  return wx.getStorageSync(key) || fallback
}

function write(key, value) {
  wx.setStorageSync(key, value)
  return value
}

function getFavorites() {
  return read(FAVORITES_KEY, [])
}

function isFavorite(jobId) {
  return getFavorites().some((item) => item.id === jobId)
}

function toggleFavorite(job) {
  const list = getFavorites()
  const exists = list.some((item) => item.id === job.id)
  const next = exists
    ? list.filter((item) => item.id !== job.id)
    : [{ ...job, favorited_at: Date.now() }].concat(list)
  write(FAVORITES_KEY, next)
  return !exists
}

async function syncFavoritesFromRemote() {
  try {
    const value = await api().getRemoteSetting("favorite_jobs")
    if (Array.isArray(value)) return write(FAVORITES_KEY, value)
  } catch (error) {
    // 本地兜底即可。
  }
  return getFavorites()
}

async function saveFavoritesSynced(list) {
  write(FAVORITES_KEY, list)
  try {
    await api().putRemoteSetting("favorite_jobs", list)
  } catch (error) {
    // 网络或登录态失败时，本地收藏仍然有效。
  }
  return list
}

function toggleFavoriteSynced(job) {
  const list = getFavorites()
  const exists = list.some((item) => item.id === job.id)
  const next = exists
    ? list.filter((item) => item.id !== job.id)
    : [{ ...job, favorited_at: Date.now() }].concat(list)
  write(FAVORITES_KEY, next)
  saveFavoritesSynced(next)
  return !exists
}

function getSubscriptions() {
  return read(SUBSCRIPTIONS_KEY, [
    {
      id: "default-shenzhen",
      name: "全深圳教师岗位",
      district: "全深圳",
      stage: "不限",
      subject: "不限",
      bianzhi: "不限",
      enabled: true
    }
  ])
}

function saveSubscriptions(list) {
  return write(SUBSCRIPTIONS_KEY, list)
}

function normalizeRemoteRule(item) {
  return {
    id: item.id,
    name: item.name,
    district: (item.districts || []).join("、") || "全深圳",
    stage: (item.stages || []).join("、") || "不限",
    subject: (item.subjects || []).join("、") || "不限",
    bianzhi: item.require_bianzhi ? "优先编制" : "不限",
    enabled: item.active !== false
  }
}

async function syncSubscriptionsFromRemote() {
  try {
    const remote = await api().getRemoteRules()
    if (Array.isArray(remote) && remote.length > 0) {
      return { source: "云端", list: saveSubscriptions(remote.map(normalizeRemoteRule)) }
    }
  } catch (error) {
    // 本地兜底即可。
  }
  return { source: "本地", list: getSubscriptions() }
}

async function addSubscriptionSynced(rule) {
  const localNext = saveSubscriptions([rule].concat(getSubscriptions()))
  try {
    const remote = await api().createRemoteRule(rule)
    const normalized = normalizeRemoteRule(remote)
    const next = [normalized].concat(getSubscriptions().filter((item) => item.id !== rule.id))
    saveSubscriptions(next)
    return { synced: true, list: next, rule: normalized }
  } catch (error) {
    return { synced: false, list: localNext, rule }
  }
}

async function updateSubscriptionSynced(rule, list) {
  saveSubscriptions(list)
  if (!String(rule.id).startsWith("rule-") && !String(rule.id).startsWith("default-")) {
    try {
      await api().updateRemoteRule(rule)
      return { synced: true, list }
    } catch (error) {
      // 本地兜底即可。
    }
  }
  return { synced: false, list }
}

function getResumes() {
  return read(RESUMES_KEY, [
    {
      id: "resume-default",
      name: "深圳教师求职简历",
      completeness: 62,
      updated_at: "待完善",
      highlights: ["教资/普通话", "教学经历", "获奖与证书"]
    }
  ])
}

function saveResumes(list) {
  return write(RESUMES_KEY, list)
}

function normalizeRemoteResume(item) {
  return {
    id: item.id,
    name: item.name || "教师简历",
    summary: item.summary || "",
    file_url: item.file_url || "local://resume-placeholder",
    is_default: Boolean(item.is_default),
    completeness: item.summary ? 82 : 45,
    updated_at: item.updated_at ? String(item.updated_at).slice(0, 10) : "已上传",
    highlights: String(item.summary || "基本信息、目标岗位、待补教学成果")
      .split(/[、,，;；\s]+/)
      .filter(Boolean)
      .slice(0, 3)
  }
}

async function syncResumesFromRemote() {
  try {
    const remote = await api().getRemoteResumes()
    if (Array.isArray(remote) && remote.length > 0) {
      return { source: "云端", list: saveResumes(remote.map(normalizeRemoteResume)) }
    }
  } catch (error) {
    // 本地兜底即可。
  }
  return { source: "本地", list: getResumes() }
}

async function addResumeSynced(resume) {
  const localNext = saveResumes([resume].concat(getResumes()))
  try {
    const remote = await api().createRemoteResume(resume)
    const normalized = normalizeRemoteResume(remote)
    const next = [normalized].concat(getResumes().filter((item) => item.id !== resume.id))
    saveResumes(next)
    return { synced: true, list: next, resume: normalized }
  } catch (error) {
    return { synced: false, list: localNext, resume }
  }
}

async function uploadResumeSynced(filePath, name) {
  const remote = await api().uploadRemoteResume(filePath, name)
  const normalized = normalizeRemoteResume(remote)
  const next = saveResumes([normalized].concat(getResumes().filter((item) => item.id !== normalized.id)))
  return { synced: true, list: next, resume: normalized }
}

async function updateResumeSynced(resume) {
  const localNext = saveResumes(getResumes().map((item) => (
    item.id === resume.id ? { ...item, ...resume, updated_at: "刚刚" } : item
  )))
  try {
    const remote = await api().updateRemoteResume(resume)
    const normalized = normalizeRemoteResume(remote)
    const next = saveResumes(getResumes().map((item) => (
      item.id === resume.id ? normalized : item
    )))
    return { synced: true, list: next, resume: normalized }
  } catch (error) {
    return { synced: false, list: localNext, resume }
  }
}

async function deleteResumeSynced(id) {
  const localNext = saveResumes(getResumes().filter((item) => item.id !== id))
  try {
    await api().deleteRemoteResume(id)
    return { synced: true, list: localNext }
  } catch (error) {
    return { synced: false, list: localNext }
  }
}

function getProfileDraft() {
  return read(PROFILE_DRAFT_KEY, {
    districts: "全深圳",
    stages: "小学、初中、高中",
    subjects: "语文、数学、英语、音乐、体育、美术",
    certificate: "待补充",
    years: "待补充",
    schoolType: "公办、民办均可"
  })
}

function saveProfileDraft(profile) {
  return write(PROFILE_DRAFT_KEY, profile)
}

function profileToDraft(profile = {}) {
  const intro = String(profile.intro || "")
  const getIntroValue = (label) => {
    const match = intro.match(new RegExp(`${label}:([^;；]+)`))
    return match ? match[1] : ""
  }
  return {
    real_name: profile.real_name || "",
    email: profile.email || "",
    education: getIntroValue("学历"),
    major: getIntroValue("专业"),
    districts: (profile.target_districts || []).join("、") || "全深圳",
    stages: (profile.target_stages || []).join("、") || "小学、初中、高中",
    subjects: (profile.target_subjects || []).join("、") || "",
    certificate: profile.cert_no || "",
    years: getIntroValue("经验"),
    schoolType: getIntroValue("学校偏好") || "公办、民办均可"
  }
}

async function syncProfileDraftFromRemote() {
  try {
    const profile = await api().getProfile()
    const draft = profileToDraft(profile)
    return { source: "云端", form: saveProfileDraft({ ...getProfileDraft(), ...draft }) }
  } catch (error) {
    // 本地兜底即可。
  }
  return { source: "本地", form: getProfileDraft() }
}

function getLocalApplications() {
  return read(LOCAL_APPLICATIONS_KEY, [])
}

function addLocalApplication(record) {
  const list = getLocalApplications()
  const next = [{
    id: `local-application-${Date.now()}`,
    status: "待处理",
    sent_at: "",
    created_at: Date.now(),
    ...record
  }].concat(list)
  return write(LOCAL_APPLICATIONS_KEY, next)
}

function updateLocalApplicationStatus(id, status) {
  const next = getLocalApplications().map((item) => (
    item.id === id ? { ...item, status, updated_at: Date.now() } : item
  ))
  return write(LOCAL_APPLICATIONS_KEY, next)
}

function addLocalApplicationNote(id, note) {
  const content = String(note || "").trim()
  if (!content) return getLocalApplications()
  const next = getLocalApplications().map((item) => {
    if (item.id !== id) return item
    const notes = Array.isArray(item.notes) ? item.notes : []
    return {
      ...item,
      notes: [{ content, created_at: Date.now() }].concat(notes).slice(0, 8),
      updated_at: Date.now()
    }
  })
  return write(LOCAL_APPLICATIONS_KEY, next)
}

async function syncLocalApplicationsFromRemote() {
  try {
    const value = await api().getRemoteSetting("local_applications")
    if (Array.isArray(value)) return write(LOCAL_APPLICATIONS_KEY, value)
  } catch (error) {
    // 本地兜底即可。
  }
  return getLocalApplications()
}

async function saveLocalApplicationsSynced(list) {
  write(LOCAL_APPLICATIONS_KEY, list)
  try {
    await api().putRemoteSetting("local_applications", list)
  } catch (error) {
    // 网络或登录态失败时，本地保存仍然有效。
  }
  return list
}

function addLocalApplicationSynced(record) {
  const list = getLocalApplications()
  const next = [{
    id: `local-application-${Date.now()}`,
    status: "待处理",
    sent_at: "",
    created_at: Date.now(),
    ...record
  }].concat(list)
  write(LOCAL_APPLICATIONS_KEY, next)
  saveLocalApplicationsSynced(next)
  return next[0]
}

function updateLocalApplicationStatusSynced(id, status) {
  const next = updateLocalApplicationStatus(id, status)
  saveLocalApplicationsSynced(next)
  return next
}

function addLocalApplicationNoteSynced(id, note) {
  const next = addLocalApplicationNote(id, note)
  saveLocalApplicationsSynced(next)
  return next
}

function defaultNotificationPreferences() {
  return {
    deadline: true,
    application: true,
    materials: true,
    daily: false,
    days_before: 3,
    quiet_start: "22:00",
    quiet_end: "08:00"
  }
}

function getNotificationPreferences() {
  return read(NOTIFICATION_PREFS_KEY, defaultNotificationPreferences())
}

async function syncNotificationPreferencesFromRemote() {
  try {
    const value = await api().getRemoteSetting("notification_preferences")
    if (value && typeof value === "object" && !Array.isArray(value) && Object.keys(value).length > 0) {
      const prefs = { ...defaultNotificationPreferences(), ...value }
      return { source: "云端", value: write(NOTIFICATION_PREFS_KEY, prefs) }
    }
  } catch (error) {
    // 本地兜底即可。
  }
  return { source: "本地", value: getNotificationPreferences() }
}

async function saveNotificationPreferencesSynced(preferences) {
  const value = { ...defaultNotificationPreferences(), ...preferences }
  write(NOTIFICATION_PREFS_KEY, value)
  try {
    await api().putRemoteSetting("notification_preferences", value)
    return { synced: true, value }
  } catch (error) {
    return { synced: false, value }
  }
}

function getMaterials() {
  return read(MATERIALS_KEY, null)
}

function saveMaterials(list) {
  return write(MATERIALS_KEY, list)
}

async function syncMaterialsFromRemote(fallback = null) {
  try {
    const value = await api().getRemoteSetting("materials_checklist")
    if (Array.isArray(value) && value.length > 0) return write(MATERIALS_KEY, value)
  } catch (error) {
    // 本地兜底即可。
  }
  return fallback !== null ? fallback : getMaterials()
}

async function saveMaterialsSynced(list) {
  saveMaterials(list)
  try {
    await api().putRemoteSetting("materials_checklist", list)
  } catch (error) {
    // 网络或登录态失败时，本地保存仍然有效。
  }
  return list
}

function getSavedSearches() {
  return read(SAVED_SEARCHES_KEY, [])
}

function saveSavedSearches(list) {
  return write(SAVED_SEARCHES_KEY, list.slice(0, 6))
}

async function syncSavedSearchesFromRemote() {
  try {
    const value = await api().getRemoteSetting("saved_searches")
    if (Array.isArray(value)) return write(SAVED_SEARCHES_KEY, value.slice(0, 6))
  } catch (error) {
    // 本地兜底即可。
  }
  return getSavedSearches()
}

async function saveSavedSearchesSynced(list) {
  const next = saveSavedSearches(list)
  try {
    await api().putRemoteSetting("saved_searches", next)
  } catch (error) {
    // 网络或登录态失败时，本地保存仍然有效。
  }
  return next
}

module.exports = {
  addLocalApplication,
  addLocalApplicationNoteSynced,
  addLocalApplicationSynced,
  getFavorites,
  getLocalApplications,
  getMaterials,
  getNotificationPreferences,
  getProfileDraft,
  getResumes,
  getSavedSearches,
  getSubscriptions,
  isFavorite,
  saveFavoritesSynced,
  saveLocalApplicationsSynced,
  saveMaterials,
  saveMaterialsSynced,
  saveNotificationPreferencesSynced,
  saveProfileDraft,
  saveResumes,
  saveSavedSearches,
  saveSavedSearchesSynced,
  saveSubscriptions,
  deleteResumeSynced,
  syncSubscriptionsFromRemote,
  syncFavoritesFromRemote,
  syncLocalApplicationsFromRemote,
  syncMaterialsFromRemote,
  syncNotificationPreferencesFromRemote,
  syncProfileDraftFromRemote,
  syncResumesFromRemote,
  syncSavedSearchesFromRemote,
  toggleFavorite,
  toggleFavoriteSynced,
  addSubscriptionSynced,
  addResumeSynced,
  uploadResumeSynced,
  updateResumeSynced,
  updateSubscriptionSynced,
  updateLocalApplicationStatus,
  updateLocalApplicationStatusSynced
}
