"""Render Nginx config for the API domain from the template."""
from __future__ import annotations

import re
import sys
from pathlib import Path


DOMAIN_RE = re.compile(r"^(?!-)[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$")


def main() -> int:
    if len(sys.argv) not in {2, 3}:
        print("Usage: python3 scripts/render_nginx_config.py api.your-domain.com [output.conf]")
        return 2

    domain = sys.argv[1].strip().lower()
    if not DOMAIN_RE.match(domain):
        print("域名格式不对。例子：api.example.com")
        return 1

    root = Path(__file__).resolve().parents[1]
    template = root / "deploy" / "nginx.teacher-job-api.conf"
    output = Path(sys.argv[2]) if len(sys.argv) == 3 else root / "dist" / f"nginx.{domain}.conf"
    output.parent.mkdir(parents=True, exist_ok=True)
    text = template.read_text(encoding="utf-8").replace("api.your-domain.com", domain)
    output.write_text(text, encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
