"""第二层：LLM 智能匹配（DeepSeek）—— 真实实现。

已实现：可解释评分 prompt、调用封装、健壮 JSON 解析（带重试与兜底）。
开发期 settings.LLM_STUB_MODE=1 走占位实现，无需 API Key 即可跑通全链路；
设为 0 并配好 DEEPSEEK_API_KEY 即启用真实匹配。
"""
from __future__ import annotations

import json
import re

from config import settings

# 评分契约 + 反虚构 + 可解释。这是匹配质量的核心。
SYSTEM_PROMPT = """你是教师招聘匹配助手。根据【候选人简历】【求职意向】【岗位 JD】，
评估候选人与该岗位的契合度并输出结构化结果。

评分维度（综合给出 0-100 的 score）：
- 硬条件：区域、学段、学科、编制是否符合（不符合应显著降低分数）；
- 隐性要求：从 JD 中识别偏好（如"需班主任经验""接受调剂""优先竞赛辅导经历"），
  与候选人简历逐项比对；
- 整体胜任度与亮点匹配。

严格要求：
- 只依据候选人简历中真实存在的信息，不得臆测或编造其经历；
- 命中点要具体、可对应到简历与 JD 的内容；
- 求职信草稿只能使用候选人真实信息，措辞专业、针对该校该岗。

只输出一个 JSON 对象，不要任何多余文字、解释或 Markdown 代码块：
{
  "score": 0-100 的整数,
  "matched_points": ["具体命中点，如 '学科匹配:语文'", "'JD要求班主任,简历有班主任经历'"],
  "gaps": ["JD要求但简历未体现的点，如实列出；没有则空数组"],
  "reason": "一句话综合理由，需对应上面的命中点与差距",
  "cover_letter": "针对该校该岗位的求职信草稿（150-300字）"
}"""


def _stub_result(resume_summary: str, jd_text: str) -> dict:
    """占位实现：确定性合理结果，让管道在无 API Key 时也能端到端跑通。"""
    return {
        "score": 75,
        "matched_points": ["（占位）学科/区域基本匹配"],
        "gaps": [],
        "reason": "（占位结果）开发模式未调用真实 LLM。设 LLM_STUB_MODE=0 启用 DeepSeek。",
        "cover_letter": "尊敬的招聘负责人：您好，我对贵校教师岗位很感兴趣……（占位草稿）",
    }


def _call_deepseek(system: str, user: str) -> str:
    """调用 DeepSeek chat completions，返回模型文本。需 httpx 与有效 API Key。"""
    import httpx

    resp = httpx.post(
        f"{settings.DEEPSEEK_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}"},
        json={
            "model": settings.DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.3,
            "response_format": {"type": "json_object"},
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _extract_json(text: str) -> dict:
    """从模型输出里稳健取出 JSON 对象（容忍代码块包裹与前后噪声）。"""
    cleaned = re.sub(r"```(?:json)?|```", "", text).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)  # 退一步：取首个 {...}
        if not m:
            raise
        return json.loads(m.group(0))


def _normalize(data: dict) -> dict:
    """字段裁剪与边界保护。"""
    try:
        score = max(0, min(100, int(data.get("score"))))
    except (TypeError, ValueError):
        score = None
    return {
        "score": score,
        "matched_points": list(data.get("matched_points") or []),
        "gaps": list(data.get("gaps") or []),
        "reason": data.get("reason"),
        "cover_letter": data.get("cover_letter"),
    }


def match_resume_to_job(resume_summary: str, jd_text: str, intent: dict | None = None) -> dict:
    """对单个(简历, 岗位)产出结构化匹配结果。失败不抛，返回 score=None 兜底。"""
    if settings.LLM_STUB_MODE:
        return _stub_result(resume_summary, jd_text)

    user_prompt = (
        f"【候选人简历】\n{resume_summary}\n\n"
        f"【求职意向】\n{json.dumps(intent or {}, ensure_ascii=False)}\n\n"
        f"【岗位 JD】\n{jd_text}"
    )

    last_err = None
    for _ in range(2):  # 最多重试一次
        try:
            return _normalize(_extract_json(_call_deepseek(SYSTEM_PROMPT, user_prompt)))
        except Exception as e:
            last_err = e
    return {
        "score": None, "matched_points": [], "gaps": [],
        "reason": f"LLM 匹配失败：{last_err}", "cover_letter": None,
    }
