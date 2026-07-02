from __future__ import annotations

from pathlib import Path


def _compact(text: str, limit: int = 420) -> str:
    lines = [line.strip() for line in text.replace("\r", "\n").split("\n")]
    compact = "；".join(line for line in lines if line)
    return compact[:limit]


def _read_text(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            return path.read_text(encoding=encoding, errors="ignore")
        except UnicodeDecodeError:
            continue
    return path.read_text(errors="ignore")


def _read_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages[:3]:
        try:
            parts.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001
            continue
    return "\n".join(parts)


def summarize_resume_file(path: Path) -> tuple[str, str]:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md"}:
        text = _read_text(path)
        summary = _compact(text)
        return summary, "已从文本文件提取摘要"

    if suffix == ".pdf":
        text = _read_pdf(path)
        summary = _compact(text)
        if summary:
            return summary, "已从 PDF 前 3 页提取摘要"
        return "", "PDF 暂未提取到可用文字，可能是扫描件"

    if suffix in {".doc", ".docx"}:
        return "", "Word 文件已保存；当前演示版暂不解析 Word 内容，请手动补充摘要"

    return "", "文件已保存；当前格式暂不自动解析，请手动补充摘要"
