"""发信服务（把简历发到招聘方邮箱）—— 真实实现。

默认 settings.MAILER_DRY_RUN=1 时只记录日志、不真正发送（开发避免误发）。
配好 SMTP_* 并设 MAILER_DRY_RUN=0 即真实发送。
注意：生产务必配好发信域名的 SPF/DKIM，否则简历邮件大概率进垃圾箱。
默认走 465 SSL；若用 587 STARTTLS 需自行改用 smtplib.SMTP + starttls()。
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from urllib.parse import urlparse

from config import settings

logger = logging.getLogger("mailer")


def _download(url: str) -> tuple[bytes, str]:
    """下载附件，返回 (字节, 文件名)。"""
    import httpx

    r = httpx.get(url, timeout=60, follow_redirects=True)
    r.raise_for_status()
    name = urlparse(url).path.rsplit("/", 1)[-1] or "resume.pdf"
    return r.content, name


def send_resume(
    to_email: str,
    subject: str,
    body: str,
    attachment_url: str | None = None,
) -> dict:
    """发送一封带简历附件的邮件。返回 {"ok": bool, "error": str|None}。"""
    if settings.MAILER_DRY_RUN or not settings.SMTP_HOST:
        logger.info("[DRY-RUN] 邮件未实际发送 → %s | 主题:%s | 附件:%s",
                    to_email, subject, attachment_url)
        return {"ok": True, "error": None}

    try:
        msg = EmailMessage()
        msg["From"] = settings.SMTP_FROM or settings.SMTP_USER
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.set_content(body or "您好，随信附上本人简历，期待贵校回复。")

        if attachment_url:
            data, fname = _download(attachment_url)
            subtype = "pdf" if fname.lower().endswith(".pdf") else "octet-stream"
            msg.add_attachment(data, maintype="application", subtype=subtype, filename=fname)

        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, context=ctx) as s:
            s.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            s.send_message(msg)
        return {"ok": True, "error": None}
    except Exception as e:  # noqa: BLE001
        logger.exception("邮件发送失败 → %s", to_email)
        return {"ok": False, "error": str(e)}
