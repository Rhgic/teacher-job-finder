const config = require("./utils/config")

App({
  globalData: {
    apiBase: config.apiBase,
    subscribeTemplates: config.subscribeTemplates || {},
    openid: "demo-openid"
  }
})
