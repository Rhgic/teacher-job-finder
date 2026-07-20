"""简历 PDF → structured_content 的轻量解析。

目标是先把 PDF 文本抽出来并按常见简历栏目粗分块，便于后续 LLM 改写读取。
解析不到时返回 None，不阻塞用户手填 structured_content。
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlparse


SECTION_ALIASES = {
    "basic": ("基本信息", "个人信息", "联系方式", "求职意向"),
    "education": ("教育背景", "教育经历", "学历背景"),
    "experience": ("工作经历", "实习经历", "实践经历", "教学经历", "校园经历"),
    "projects": ("项目经历", "项目经验"),
    "skills": ("技能", "专业技能", "证书", "资格证书", "荣誉证书"),
    "self_eval": ("自我评价", "个人评价", "个人总结", "自我介绍"),
}


def parse_resume_pdf(file_url: str) -> dict | None:
    """从本地 PDF 路径抽取结构化内容；非本地文件或失败则返回 None。"""
    path = _local_path_from_url(file_url)
    if path is None or not path.exists() or path.suffix.lower() != ".pdf":
        return None
    text = _extract_pdf_text(path)
    if not text:
        return None
    return structure_resume_text(text)


def structure_resume_text(text: str) -> dict:
    text = _normalize_text(text)
    sections: dict[str, list[str]] = {key: [] for key in SECTION_ALIASES}
    sections["raw_text"] = [text]

    current = "basic"
    for line in text.splitlines():
        heading = _match_heading(line)
        if heading:
            current = heading
            continue
        if line.strip():
            sections.setdefault(current, []).append(line.strip())

    result: dict[str, object] = {}
    for key, lines in sections.items():
        if not lines:
            continue
        if key == "raw_text":
            result[key] = "\n".join(lines)
        elif key == "basic":
            result[key] = _parse_basic(lines)
        else:
            result[key] = lines
    return result


def _local_path_from_url(file_url: str) -> Path | None:
    if not file_url:
        return None
    parsed = urlparse(file_url)
    if parsed.scheme in ("http", "https", "cos"):
        return None
    if parsed.scheme == "file":
        return Path(unquote(parsed.path))
    return Path(unquote(file_url)).expanduser()


def _extract_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        reader = PdfReader(str(path))
        pages = [(page.extract_text() or "") for page in reader.pages]
    except Exception:
        return ""
    return "\n".join(pages)


def _normalize_text(text: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _match_heading(line: str) -> str | None:
    clean = re.sub(r"[:：\s]+", "", line)
    if len(clean) > 12:
        return None
    for key, aliases in SECTION_ALIASES.items():
        if any(alias == clean or alias in clean for alias in aliases):
            return key
    return None


def _parse_basic(lines: list[str]) -> dict:
    text = "\n".join(lines)
    email = _first_match(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    phone = _first_match(r"1[3-9]\d{9}", text)
    name = lines[0] if lines else ""
    return {
        "name": name,
        "phone": phone,
        "email": email,
        "summary": lines,
    }


def _first_match(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text)
    return match.group(0) if match else None
