from __future__ import annotations

import json
from dataclasses import dataclass
from os import getenv
from urllib.error import URLError
from urllib.request import Request, urlopen

from models import Job, Resume, SubRule, UserProfile


@dataclass(frozen=True)
class LlmMatchOutput:
    score: int
    matched_points: list[str]
    gaps: list[str]
    reason: str
    cover_letter: str


SYSTEM_PROMPT = (
    "你是教师招聘匹配助手。请只输出 JSON,无多余文字。"
    "JSON 字段必须为 score, matched_points, gaps, reason, cover_letter。"
    "score 是 0-100 整数; matched_points/gaps 是字符串数组。"
)


def is_deepseek_configured() -> bool:
    return bool(getenv("DEEPSEEK_API_KEY"))


def build_user_prompt(
    job: Job, rule: SubRule, profile: UserProfile | None, resume: Resume | None
) -> str:
    profile_text = "未填写"
    if profile:
        profile_text = (
            f"姓名:{profile.real_name or '未填写'};"
            f"目标区域:{','.join(profile.target_districts or [])};"
            f"目标学段:{','.join(profile.target_stages or [])};"
            f"目标学科:{','.join(profile.target_subjects or [])};"
            f"期望薪资:{profile.expected_salary_min or '-'}-{profile.expected_salary_max or '-'};"
            f"自我介绍:{profile.intro or ''}"
        )
    resume_text = resume.summary if resume and resume.summary else "暂无简历摘要"
    rule_text = (
        f"区域:{','.join(rule.districts or [])};"
        f"学段:{','.join(rule.stages or [])};"
        f"学科:{','.join(rule.subjects or [])};"
        f"薪资:{rule.salary_min or '-'}-{rule.salary_max or '-'};"
        f"要求编制:{rule.require_bianzhi}"
    )
    jd_text = (
        f"岗位:{job.title};学校:{job.school_name};区域:{job.district};"
        f"学段:{job.stage};学科:{job.subject};编制:{job.has_bianzhi};"
        f"薪资:{job.salary_min or '-'}-{job.salary_max or '-'};JD:{job.jd}"
    )
    return f"用户画像:{profile_text}\n简历摘要:{resume_text}\n订阅规则:{rule_text}\n岗位JD:{jd_text}"


def fallback_match(job: Job, rule: SubRule, resume: Resume | None) -> LlmMatchOutput:
    score = 58
    matched_points: list[str] = []
    gaps: list[str] = []

    if job.district in (rule.districts or []):
        score += 10
        matched_points.append(f"区域匹配:{job.district}")
    if job.stage in (rule.stages or []):
        score += 8
        matched_points.append(f"学段匹配:{job.stage}")
    if job.subject in (rule.subjects or []):
        score += 12
        matched_points.append(f"学科匹配:{job.subject}")
    if job.has_bianzhi:
        score += 4
        matched_points.append("岗位含编制")
    if resume and resume.summary:
        for keyword in ("班主任", "校队", "体育", "教学", "训练"):
            if keyword in resume.summary and keyword in job.jd:
                score += 3
                matched_points.append(f"简历与JD共同提到:{keyword}")

    if rule.require_bianzhi and not job.has_bianzhi:
        score -= 18
        gaps.append("订阅规则要求编制,该岗位未标注编制")
    if job.subject not in (rule.subjects or []):
        gaps.append(f"岗位学科为{job.subject},不在优先学科内")
    if not gaps:
        gaps.append("暂无明显硬性缺口,建议进一步查看公告原文")

    score = max(0, min(100, score))
    reason = "、".join(matched_points[:3]) if matched_points else "岗位基础条件可进一步评估"
    cover_letter = (
        f"尊敬的{job.school_name}招聘负责人:您好!我希望应聘贵校{job.subject}教师岗位。"
        "我认同学校育人理念,愿结合个人教学经历与岗位要求,承担课堂教学、班级管理及相关活动组织工作。"
        "期待获得进一步沟通机会。"
    )
    return LlmMatchOutput(score, matched_points, gaps, reason, cover_letter)


def parse_llm_json(raw: str) -> LlmMatchOutput:
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end < start:
        raise ValueError("LLM response is not JSON")
    data = json.loads(raw[start : end + 1])
    return LlmMatchOutput(
        score=max(0, min(100, int(data["score"]))),
        matched_points=list(data.get("matched_points") or []),
        gaps=list(data.get("gaps") or []),
        reason=str(data.get("reason") or ""),
        cover_letter=str(data.get("cover_letter") or ""),
    )


def call_deepseek(prompt: str, timeout: int = 20) -> LlmMatchOutput:
    api_key = getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured")

    payload = json.dumps(
        {
            "model": getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
    ).encode("utf-8")
    request = Request(
        "https://api.deepseek.com/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read().decode("utf-8"))
    content = body["choices"][0]["message"]["content"]
    return parse_llm_json(content)


def match_job(
    job: Job,
    rule: SubRule,
    profile: UserProfile | None,
    resume: Resume | None,
) -> LlmMatchOutput:
    prompt = build_user_prompt(job, rule, profile, resume)
    try:
        return call_deepseek(prompt)
    except (RuntimeError, ValueError, KeyError, URLError, TimeoutError, OSError):
        return fallback_match(job, rule, resume)
