// dev: local backend in WeChat DevTools.
// prod: public HTTPS backend for audit/release.
const ENV = "dev"

const CONFIG = {
  dev: {
    apiBase: "http://192.168.31.76:8000",
    subscribeTemplates: {
      deadline: "",
      application: "",
      materials: "",
      daily: ""
    }
  },
  prod: {
    // 发布前改成你的 HTTPS 后端域名，并在微信公众平台配置为 request 合法域名。
    apiBase: "https://api.example.com",
    // 发布前在微信公众平台申请订阅消息模板后填入模板 ID。
    subscribeTemplates: {
      deadline: "",
      application: "",
      materials: "",
      daily: ""
    }
  }
}

module.exports = {
  ENV,
  ...CONFIG[ENV]
}
