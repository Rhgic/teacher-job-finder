import { spawnSync } from "node:child_process"
import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..")
const releaseMode = process.argv.includes("--release")

function listFiles(dir, predicate) {
  const result = []
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) {
      result.push(...listFiles(full, predicate))
    } else if (predicate(full)) {
      result.push(full)
    }
  }
  return result
}

function run(name, command, args, options = {}) {
  console.log(`\n== ${name} ==`)
  const result = spawnSync(command, args, {
    cwd: options.cwd || root,
    encoding: "utf8"
  })
  if (result.stdout) process.stdout.write(result.stdout)
  if (result.stderr) process.stderr.write(result.stderr)
  if (result.status !== 0) {
    console.log(`✗ ${name} 失败`)
    return false
  }
  console.log(`✓ ${name} 通过`)
  return true
}

let ok = true

const jsFiles = listFiles(root, (file) => /\.(js|mjs)$/.test(file))
  .filter((file) => !file.includes(`${path.sep}node_modules${path.sep}`))
for (const file of jsFiles) {
  ok = run(`JS 语法 ${path.relative(root, file)}`, "node", ["--check", file]) && ok
}

const jsonFiles = listFiles(root, (file) => /\.json$/.test(file))
for (const file of jsonFiles) {
  ok = run(`JSON 格式 ${path.relative(root, file)}`, "python3", [
    "-c",
    "import json,sys; json.load(open(sys.argv[1], encoding='utf-8'))",
    file
  ]) && ok
}

ok = run("岗位标题拼接断言", "node", ["scripts/test-build-job-title.mjs"]) && ok
ok = run("开发后端健康检查", "node", ["scripts/dev-health-check.mjs"]) && ok

if (releaseMode) {
  ok = run("正式发布配置检查", "node", ["scripts/release-check.mjs"]) && ok
} else {
  console.log("\n提示：正式发布前请额外运行 node scripts/check-all.mjs --release")
}

process.exit(ok ? 0 : 1)
