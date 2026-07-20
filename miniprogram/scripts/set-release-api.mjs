import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"

const apiBase = process.argv[2]

if (!apiBase) {
  console.error("Usage: node scripts/set-release-api.mjs https://api.your-domain.com")
  process.exit(1)
}

let parsed
try {
  parsed = new URL(apiBase)
} catch {
  console.error("API 地址格式不对。例子：https://api.your-domain.com")
  process.exit(1)
}

if (parsed.protocol !== "https:") {
  console.error("正式发布必须使用 https:// 开头的后端域名。")
  process.exit(1)
}

if (parsed.hostname === "localhost" || parsed.hostname === "127.0.0.1") {
  console.error("正式发布不能使用 localhost 或 127.0.0.1。")
  process.exit(1)
}

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..")
const configPath = path.join(root, "utils", "config.js")
let config = fs.readFileSync(configPath, "utf8")

config = config.replace(/const\s+ENV\s*=\s*["'][^"']+["']/, 'const ENV = "prod"')
config = config.replace(
  /(prod:\s*{[\s\S]*?apiBase:\s*)["'][^"']+["']/,
  `$1"${apiBase.replace(/\/$/, "")}"`
)

fs.writeFileSync(configPath, config)
console.log(`已切到正式环境：${apiBase.replace(/\/$/, "")}`)
