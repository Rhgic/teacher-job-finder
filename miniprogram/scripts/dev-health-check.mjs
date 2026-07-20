import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..")
const configPath = path.join(root, "utils", "config.js")
const config = fs.readFileSync(configPath, "utf8")
const devApiMatch = config.match(/dev:\s*{[\s\S]*?apiBase:\s*["']([^"']+)["']/)
const apiBase = devApiMatch?.[1]

if (!apiBase) {
  console.error("没有找到 dev.apiBase")
  process.exit(1)
}

async function check(name, fn) {
  try {
    await fn()
    console.log(`✓ ${name}`)
  } catch (error) {
    console.log(`✗ ${name}: ${error.message}`)
    return false
  }
  return true
}

let ok = true

ok = await check("后端健康 /health", async () => {
  const res = await fetch(`${apiBase}/health`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const data = await res.json()
  if (data.status !== "ok") throw new Error("status 不是 ok")
}) && ok

ok = await check("上线准备 /readiness", async () => {
  const res = await fetch(`${apiBase}/readiness`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const data = await res.json()
  if (!data || !data.required || !data.counts) throw new Error("响应结构不完整")
  if (!data.backup || typeof data.backup !== "object") {
    throw new Error("响应缺少 backup 备份状态")
  }
  if (!data.required.wechat_secret) {
    console.log("  提示：WECHAT_SECRET 未配置，正式登录前需要补。")
  }
  if (!data.required.auth_dev_mode_off) {
    console.log("  提示：AUTH_DEV_MODE 仍是开发模式，正式上线前要改成 0。")
  }
  if (data.backup.ok) {
    console.log(`  备份状态：已发现 ${data.backup.count || 0} 份备份。`)
  } else {
    console.log("  提示：暂未发现数据库备份，服务器上线前要启用备份定时器。")
  }
}) && ok

ok = await check("岗位接口 /jobs", async () => {
  const res = await fetch(`${apiBase}/jobs`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const data = await res.json()
  if (!Array.isArray(data)) throw new Error("响应不是数组")
  if (data.length > 0 && !("source_url" in data[0])) {
    throw new Error("岗位缺少 source_url，前端来源核验无法使用真实来源")
  }
}) && ok

ok = await check("用户设置接口 /settings", async () => {
  for (const key of ["saved_searches", "materials_checklist", "favorite_jobs", "local_applications"]) {
    const res = await fetch(`${apiBase}/settings/${key}`)
    if (!res.ok) throw new Error(`${key} HTTP ${res.status}`)
    const data = await res.json()
    if (!data || data.key !== key || !Array.isArray(data.value)) {
      throw new Error(`${key} 设置响应结构不完整`)
    }
  }
  const notifyRes = await fetch(`${apiBase}/settings/notification_preferences`)
  if (!notifyRes.ok) throw new Error(`notification_preferences HTTP ${notifyRes.status}`)
  const notifyData = await notifyRes.json()
  if (!notifyData || notifyData.key !== "notification_preferences" || Array.isArray(notifyData.value)) {
    throw new Error("notification_preferences 设置响应结构不完整")
  }
}) && ok

ok = await check("已截止岗位投递防线", async () => {
  const jobsRes = await fetch(`${apiBase}/jobs?include_expired=true&size=100`)
  if (!jobsRes.ok) throw new Error(`/jobs HTTP ${jobsRes.status}`)
  const jobs = await jobsRes.json()
  if (!Array.isArray(jobs)) throw new Error("岗位响应不是数组")
  const today = new Date().toISOString().slice(0, 10)
  const expired = jobs.find((job) => job.deadline && job.deadline < today)
  if (!expired) {
    console.log("  提示：当前服务器没有已截止岗位，跳过投递防线实测。")
    return
  }

  const beforeRes = await fetch(`${apiBase}/applications`)
  if (!beforeRes.ok) throw new Error(`/applications HTTP ${beforeRes.status}`)
  const before = await beforeRes.json()
  if (!Array.isArray(before)) throw new Error("投递记录响应不是数组")

  const postRes = await fetch(`${apiBase}/applications`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ job_id: expired.id })
  })
  const postText = await postRes.text()
  if (postRes.status !== 400) {
    throw new Error(`已截止岗位投递应返回 400，实际 HTTP ${postRes.status}`)
  }
  if (!postText.includes("已过截止日期")) {
    throw new Error("已截止投递拒绝原因不明确")
  }

  const afterRes = await fetch(`${apiBase}/applications`)
  if (!afterRes.ok) throw new Error(`/applications HTTP ${afterRes.status}`)
  const after = await afterRes.json()
  if (!Array.isArray(after)) throw new Error("投递记录响应不是数组")
  if (after.length !== before.length) {
    throw new Error("已截止岗位被拒绝后，投递记录数量发生变化")
  }
}) && ok

await check("微信登录接口 /auth/login 已挂载", async () => {
  const res = await fetch(`${apiBase}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code: "dev-check-code" })
  })
  const text = await res.text()
  if (res.status === 404) throw new Error("接口不存在")
  if (text.includes("appsecret missing") || text.includes("jscode2session")) {
    console.log("  提示：接口存在，但服务器还没配置 WECHAT_SECRET，正式登录前需要补。")
    return
  }
  if (res.status >= 500) throw new Error(`HTTP ${res.status}`)
})

if (!ok) {
  process.exit(1)
}
