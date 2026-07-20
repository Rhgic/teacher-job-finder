# 正式上线命令清单

这份清单等你拿到正式域名和微信 AppSecret 后再用。命令不会打印密钥。

## 1. 服务器填写微信配置

```bash
cd /opt/teacher-job-api
.venv/bin/python scripts/set_env_value.py .env WECHAT_SECRET '你的微信AppSecret'
.venv/bin/python scripts/set_env_value.py .env AUTH_DEV_MODE 0
.venv/bin/python scripts/generate_session_secret.py
```

把 `generate_session_secret.py` 输出的长字符串分别填入会话密钥和后台管理令牌：

```bash
.venv/bin/python scripts/set_env_value.py .env SESSION_SECRET '刚生成的长字符串'
.venv/bin/python scripts/generate_session_secret.py
.venv/bin/python scripts/set_env_value.py .env ADMIN_API_TOKEN '第二次生成的长字符串'
sudo systemctl restart teacher-job-api
python3 scripts/check_release_env.py .env
```

## 2. 生成 Nginx 配置

把 `api.example.com` 换成你的真实 API 域名：

```bash
cd /opt/teacher-job-api
.venv/bin/python scripts/render_nginx_config.py api.example.com /tmp/teacher-job-api.conf
sudo cp /tmp/teacher-job-api.conf /etc/nginx/sites-available/teacher-job-api.conf
sudo ln -sf /etc/nginx/sites-available/teacher-job-api.conf /etc/nginx/sites-enabled/teacher-job-api.conf
sudo nginx -t
```

证书建议用 certbot：

```bash
sudo certbot --nginx -d api.example.com
sudo systemctl reload nginx
```

## 3. 微信后台配置

- 微信公众平台 -> 开发管理 -> 开发设置 -> 服务器域名
- `request 合法域名` 添加：`https://api.example.com`

## 4. 小程序切正式后端

在本机执行：

```bash
cd "/Users/rhgic/Documents/teacher job finder/miniprogram"
node scripts/set-release-api.mjs https://api.example.com
node scripts/check-all.mjs --release
```

## 5. 公网接口复查

在本机后端目录执行：

```bash
cd /Users/rhgic/Downloads/backend
python3 scripts/check_public_api.py https://api.example.com
```

全部通过后，再到微信开发者工具上传代码，并在微信公众平台提交审核。
