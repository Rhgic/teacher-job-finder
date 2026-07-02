import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..")
const configPath = path.join(root, "utils", "config.js")
const projectPath = path.join(root, "project.config.json")
const appPath = path.join(root, "app.json")
const privacyPath = path.join(root, "微信后台填写清单.md")

const config = fs.readFileSync(configPath, "utf8")
const project = JSON.parse(fs.readFileSync(projectPath, "utf8"))
const app = JSON.parse(fs.readFileSync(appPath, "utf8"))

const issues = []
const envMatch = config.match(/const\s+ENV\s*=\s*["']([^"']+)["']/)
const prodApiMatch = config.match(/prod:\s*{[\s\S]*?apiBase:\s*["']([^"']+)["']/)

const env = envMatch?.[1]
const prodApiBase = prodApiMatch?.[1]
const requiredPages = [
  "pages/jobs/index",
  "pages/recommend/index",
  "pages/applications/index",
  "pages/me/index",
  "pages/job-detail/index",
  "pages/apply-confirm/index",
  "pages/resumes/index",
  "pages/favorites/index",
  "pages/subscriptions/index",
  "pages/profile-edit/index",
  "pages/about/index",
  "pages/interview-prep/index",
  "pages/calendar/index",
  "pages/reminders/index",
  "pages/materials/index",
  "pages/source-guide/index",
  "pages/school-profile/index",
  "pages/notification-settings/index",
  "pages/job-compare/index",
  "pages/job-guide/index",
  "pages/server-status/index"
]
const requiredTabIcons = (app.tabBar?.list || []).flatMap((item) => [item.iconPath, item.selectedIconPath])
const privacyText = fs.existsSync(privacyPath) ? fs.readFileSync(privacyPath, "utf8") : ""
const ignoredFiles = new Set(
  (project.packOptions?.ignore || [])
    .filter((item) => item.type === "file")
    .map((item) => item.value)
)
const ignoredFolders = new Set(
  (project.packOptions?.ignore || [])
    .filter((item) => item.type === "folder")
    .map((item) => item.value)
)
const requiredIgnoredFiles = [
  ".DS_Store",
  "preview-info.json",
  "preview-qrcode.png",
  "project.private.config.json",
  "上线前必读.md",
  "微信后台填写清单.md",
  "审核前验收清单.md",
  "醒来后上线待办.md"
]
const requiredIgnoredFolders = ["scripts"]

if (project.appid !== "wx2dcd7d67c642d4cb") {
  issues.push(`AppID 不是当前登记值：${project.appid}`)
}

if (env !== "prod") {
  issues.push(`utils/config.js 仍是 ${env || "未知"} 环境，正式提交审核前要改成 prod`)
}

if (!prodApiBase || prodApiBase.includes("example.com")) {
  issues.push("prod.apiBase 还是示例域名，需要换成你的 HTTPS 后端域名")
}

if (prodApiBase && !prodApiBase.startsWith("https://")) {
  issues.push(`prod.apiBase 必须是 https:// 开头：${prodApiBase}`)
}

if (prodApiBase && /:\d+/.test(new URL(prodApiBase).host)) {
  issues.push("微信 request 合法域名通常不能带端口，请用标准 443 HTTPS 域名")
}

for (const page of requiredPages) {
  if (!app.pages.includes(page)) {
    issues.push(`app.json 缺少页面：${page}`)
  }
  for (const ext of ["js", "json", "wxml", "wxss"]) {
    const pageFile = path.join(root, `${page}.${ext}`)
    if (!fs.existsSync(pageFile)) {
      issues.push(`页面文件缺失：${page}.${ext}`)
    }
  }
}

for (const icon of requiredTabIcons) {
  if (!icon || !fs.existsSync(path.join(root, icon))) {
    issues.push(`tabBar 图标缺失：${icon || "空路径"}`)
  }
}

for (const keyword of ["微信登录标识", "简历", "收藏", "订阅", "投递记录"]) {
  if (!privacyText.includes(keyword)) {
    issues.push(`微信后台填写清单缺少隐私/审核关键词：${keyword}`)
  }
}

for (const file of requiredIgnoredFiles) {
  if (fs.existsSync(path.join(root, file)) && !ignoredFiles.has(file)) {
    issues.push(`开发文件未加入上传忽略：${file}`)
  }
}

for (const folder of requiredIgnoredFolders) {
  if (fs.existsSync(path.join(root, folder)) && !ignoredFolders.has(folder)) {
    issues.push(`开发目录未加入上传忽略：${folder}`)
  }
}

if (issues.length > 0) {
  console.log("上线前还有这些要处理：")
  for (const issue of issues) {
    console.log(`- ${issue}`)
  }
  process.exit(1)
}

console.log("上线前配置检查通过。")
