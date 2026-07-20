"""Check whether the public API is ready for WeChat Mini Program release."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request


def request_json(url: str, *, method: str = "GET", body: dict | None = None) -> tuple[int, object]:
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            text = response.read().decode("utf-8")
            return response.status, json.loads(text) if text else {}
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(text) if text else {}
        except json.JSONDecodeError:
            return exc.code, text
    except urllib.error.URLError as exc:  # noqa: TRY203
        print(f"访问失败：{url}")
        print(f"原因：{exc}")
        raise


def check_health(base_url: str) -> bool:
    status, data = request_json(f"{base_url}/health")
    if status != 200:
        print(f"健康检查失败：HTTP {status}")
        return False

    if not isinstance(data, dict):
        print(f"健康检查返回的不是 JSON 对象：{str(data)[:200]}")
        return False
    if data.get("status") != "ok":
        print(f"健康检查返回异常：{data}")
        return False
    print("✓ /health 正常")
    return True


def check_jobs(base_url: str) -> bool:
    status, data = request_json(f"{base_url}/jobs")
    if status != 200:
        print(f"岗位接口失败：HTTP {status}")
        return False
    if not isinstance(data, list):
        print(f"岗位接口返回的不是数组：{str(data)[:200]}")
        return False
    print(f"✓ /jobs 正常，返回 {len(data)} 条")
    return True


def check_readiness(base_url: str) -> bool:
    status, data = request_json(f"{base_url}/readiness")
    if status != 200:
        print(f"上线准备接口失败：HTTP {status}")
        return False
    if not isinstance(data, dict):
        print(f"上线准备接口返回异常：{str(data)[:200]}")
        return False
    required = data.get("required")
    if not isinstance(required, dict):
        print(f"上线准备接口缺少 required：{data}")
        return False
    backup = data.get("backup")
    if not isinstance(backup, dict):
        print(f"上线准备接口缺少 backup 运维状态：{data}")
        return False
    missing = [key for key, value in required.items() if value is not True]
    if missing:
        print(f"上线必填项未通过：{', '.join(missing)}")
        return False
    print("✓ /readiness 必填项通过")
    if backup.get("ok") is True:
        print(f"✓ 数据备份可用，当前 {backup.get('count', 0)} 份")
    else:
        print("提示：暂未发现数据库备份，建议上线前启用 backup timer")
    return True


def check_auth(base_url: str) -> bool:
    status, data = request_json(f"{base_url}/auth/login", method="POST", body={"code": "release-check-code"})
    if status == 404:
        print("微信登录接口不存在：/auth/login")
        return False
    text = json.dumps(data, ensure_ascii=False) if not isinstance(data, str) else data
    if "appsecret missing" in text or "jscode2session" in text:
        print("✓ /auth/login 已挂载；提示：WECHAT_SECRET 未配置时真实登录不会成功")
        return True
    if status >= 500:
        print(f"微信登录接口异常：HTTP {status} {text[:200]}")
        return False
    print("✓ /auth/login 已挂载")
    return True


def check_crawl_sources(base_url: str) -> bool:
    status, data = request_json(f"{base_url}/crawl/sources")
    if status != 200:
        print(f"抓取源策略接口失败：HTTP {status}")
        return False
    if not isinstance(data, dict) or not data:
        print(f"抓取源策略接口返回异常：{str(data)[:200]}")
        return False
    unsafe = [
        name
        for name, policy in data.items()
        if not isinstance(policy, dict) or policy.get("obey_robots") is not True
    ]
    if unsafe:
        print(f"这些抓取源没有开启 robots：{', '.join(unsafe)}")
        return False
    print(f"✓ /crawl/sources 正常，{len(data)} 个源已开启 robots")
    return True


def check_admin_endpoints_protected(base_url: str) -> bool:
    endpoints = [
        "/crawl/run?source=all&max_detail_pages=1",
        "/pipeline/run",
    ]
    for endpoint in endpoints:
        status, data = request_json(f"{base_url}{endpoint}", method="POST")
        if status == 200:
            print(f"公网 {endpoint} 未受保护：未带管理令牌也能触发后台任务")
            return False
        if status not in {403, 503}:
            print(f"公网 {endpoint} 保护状态异常：HTTP {status} {str(data)[:200]}")
            return False
    print("✓ 后台任务接口已拒绝未授权触发")
    return True


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/check_public_api.py https://api.your-domain.com")
        return 2

    base_url = sys.argv[1].rstrip("/")
    if not base_url.startswith("https://"):
        print("正式发布必须使用 https:// 开头的后端域名。")
        return 1

    checks = [
        check_health,
        check_readiness,
        check_jobs,
        check_auth,
        check_crawl_sources,
        check_admin_endpoints_protected,
    ]
    try:
        ok = all(check(base_url) for check in checks)
    except urllib.error.URLError:
        return 1

    if not ok:
        return 1

    print("公网后端基础接口检查通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
