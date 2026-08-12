"""简历按 JD 自动改写（见方案 5.5）—— 真实实现。

整诚红线：只能重组/突出/改措辞真实内容，严禁虚构。
本模块的双重防线：
  1) prompt 层：明确禁止虚构、要求逐条改动清单；
  2) 代码层：结构化校验，丢弃模型擅自新增的顶层字段（_strip_fabricated_keys）。
"""
from __future__ import annotations

import json
from pathlib import Path

from config import settings
from services.llm_credentials import LLMCredential
from services.llm_match import _call_deepseek, _extract_json

SYSTEM_PROMPT = """你是简历优化助手。根据岗位 JD，把候选人的结构化简历改写得更贴合该岗位。
只输出一个 JSON 对象，无多余文字：
{
  "tailored_content": {与输入结构一致的简历，已优化},
  "change_summary": [逐条说明改了什么的字符串数组]
}

【允许的操作】
- 调整经历/技能的呈现顺序，把与 JD 最相关的内容前置；
- 用 JD 的关键词复述候选人“真实做过”的事；
- 改写措辞使其更专业、更聚焦该岗位；突出已有的相关亮点。

【严禁的操作 —— 整诚红线】
- 不得新增候选人没有的经历、项目、雇主、职责；
- 不得修改学历、学位、日期、年限、证书、量化数字；
- 不得虚构或拔高任何技能水平；
- JD 要求但候选人不具备的能力：不要写进简历，可在 change_summary 里以“未覆盖:xxx”标注。
- 包括嵌套字段和列表项在内，tailored_content 不得新增字段或新增条目。

change_summary 必须逐条、可核对，让用户一眼看出每处改动都来自其真实信息。
tailored_content 的字段必须与输入简历完全相同，不得新增字段。"""


def _stub_result(structured_content: dict) -> dict:
    return {
        "tailored_content": structured_content,  # 占位：原样返回
        "change_summary": ["（占位）开发模式未调用真实 LLM。设 LLM_STUB_MODE=0 启用改写。"],
    }


def _strip_fabricated_keys(original: dict, tailored: dict) -> dict:
    """结构化反虚构：只保留原简历已有字段，并递归裁掉新增的嵌套字段 / 条目。

    这是机械防线，拦住"凭空多出一段经历/证书"这类最明显的越界；
    更细粒度的真实性仍依赖 change_summary 的人工核对。
    """
    if isinstance(original, dict) and isinstance(tailored, dict):
        cleaned = {}
        for key, value in tailored.items():
            if key not in original:
                continue
            cleaned[key] = _strip_fabricated_keys(original[key], value)
        return cleaned
    if isinstance(original, list) and isinstance(tailored, list):
        if not original:
            return []
        prototype = original[0]
        cleaned_list = []
        for item in tailored[: len(original)]:
            if isinstance(item, (dict, list)):
                cleaned_list.append(_strip_fabricated_keys(prototype, item))
            else:
                cleaned_list.append(item)
        return cleaned_list
    return tailored


def tailor_resume(structured_content: dict, jd_text: str, *,
                  cred: LLMCredential) -> dict:
    """产出改写后的简历 + 改动清单（draft，需人工审核后才可投递）。

    cred 必填，与匹配、问答同一套：改写也花用户自己的额度。
    """
    if cred.is_stub:
        return _stub_result(structured_content)

    user_prompt = (
        f"【结构化简历】\n{json.dumps(structured_content, ensure_ascii=False)}\n\n"
        f"【岗位 JD】\n{jd_text}"
    )
    try:
        data = _extract_json(_call_deepseek(SYSTEM_PROMPT, user_prompt, cred=cred))
        tailored = _strip_fabricated_keys(structured_content, data.get("tailored_content") or {})
        summary = list(data.get("change_summary") or [])
        # 若发生了字段裁剪，追加一条提示供用户知晓
        if isinstance(data.get("tailored_content"), dict) and \
                set(data["tailored_content"]) - set(structured_content):
            summary.append("（系统）已自动移除模型新增的、原简历没有的字段。")
        return {"tailored_content": tailored, "change_summary": summary}
    except Exception as e:
        return {"tailored_content": structured_content, "change_summary": [f"改写失败：{e}"]}


def _esc(x) -> str:
    import html
    return html.escape(str(x))


def _render_value(val) -> str:
    """把任意结构（字符串/列表/字典）渲染成 HTML 片段，对简历结构稳健。"""
    if isinstance(val, str):
        return f"<p>{_esc(val)}</p>"
    if isinstance(val, dict):
        rows = "".join(
            f"<div class='kv'><span class='k'>{_esc(k)}</span>"
            f"<span class='v'>{_esc(v)}</span></div>"
            for k, v in val.items()
        )
        return f"<div class='block'>{rows}</div>"
    if isinstance(val, list):
        items = []
        for it in val:
            if isinstance(it, dict):
                items.append(f"<li>{_render_value(it)}</li>")
            else:
                items.append(f"<li>{_esc(it)}</li>")
        return f"<ul>{''.join(items)}</ul>"
    return f"<p>{_esc(val)}</p>"


# 已知字段的中文小标题（未知字段直接用键名）
_SECTION_LABELS = {
    "basic": "基本信息", "education": "教育背景", "experience": "工作/实习经历",
    "skills": "技能", "self_eval": "自我评价", "projects": "项目经历",
}


def _render_html(content: dict) -> str:
    sections = []
    for key, val in (content or {}).items():
        title = _SECTION_LABELS.get(key, key)
        sections.append(f"<section><h2>{_esc(title)}</h2>{_render_value(val)}</section>")
    body = "".join(sections) or "<p>（空白简历）</p>"
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
    body{{font-family:'Noto Sans CJK SC','Microsoft YaHei',sans-serif;color:#1a1a1a;margin:36px;font-size:13px;line-height:1.6}}
    h1{{font-size:22px;margin:0 0 4px}}
    h2{{font-size:15px;border-bottom:1px solid #ccc;padding-bottom:4px;margin:18px 0 8px}}
    .kv{{display:flex;gap:8px;margin:2px 0}} .k{{color:#666;min-width:64px}}
    ul{{margin:4px 0;padding-left:18px}} li{{margin:3px 0}}
    </style></head><body>{body}</body></html>"""


def _maybe_upload_cos(local_path: str) -> str | None:
    """配置了 COS 则上传并返回 URL，否则返回 None（用本地路径）。"""
    if not (
        settings.COS_BUCKET
        and settings.COS_REGION
        and settings.COS_SECRET_ID
        and settings.COS_SECRET_KEY
    ):
        return None
    try:
        from qcloud_cos import CosConfig, CosS3Client
    except ImportError:
        # COS 是可选能力；未安装 SDK 时保持本地路径兜底，不阻断审核/投递流程。
        return None

    path = Path(local_path)
    if not path.exists() or not path.is_file():
        return None

    key = f"resumes/{path.name}"
    config = CosConfig(
        Region=settings.COS_REGION,
        SecretId=settings.COS_SECRET_ID,
        SecretKey=settings.COS_SECRET_KEY,
        Token=None,
        Scheme="https",
    )
    client = CosS3Client(config)
    client.upload_file(
        Bucket=settings.COS_BUCKET,
        LocalFilePath=str(path),
        Key=key,
        PartSize=5,
        MAXThread=2,
        EnableMD5=False,
    )
    return f"https://{settings.COS_BUCKET}.cos.{settings.COS_REGION}.myqcloud.com/{key}"


def render_to_pdf(tailored_content: dict, file_stem: str = "resume") -> str:
    """把结构化简历渲染成 PDF；配了 COS 返回 URL，否则返回本地路径。

    仅在用户审核通过后调用。需安装 weasyprint。
    """
    import os
    from weasyprint import HTML

    os.makedirs(settings.RESUME_OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(settings.RESUME_OUTPUT_DIR, f"{file_stem}.pdf")
    HTML(string=_render_html(tailored_content)).write_pdf(out_path)
    return _maybe_upload_cos(out_path) or out_path
