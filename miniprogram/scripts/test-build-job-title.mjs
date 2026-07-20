import assert from "node:assert/strict"
import { createRequire } from "node:module"

const require = createRequire(import.meta.url)
const { buildJobTitle } = require("../utils/api.js")

assert.equal(
  buildJobTitle({ school_name: "华附乐城小学", stage: "小学", subject: "语文" }),
  "华附乐城小学语文招聘"
)
assert.equal(
  buildJobTitle({ school_name: "南山实验学校", stage: "小学", subject: "语文" }),
  "南山实验学校小学语文招聘"
)
assert.equal(buildJobTitle({ subject: "体育" }), "体育招聘")
assert.equal(buildJobTitle({}), "教师招聘")

console.log("buildJobTitle assertions passed")
