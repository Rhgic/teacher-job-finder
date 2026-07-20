"""第一层：规则硬筛（已实现，毫秒级、确定性）。

管道先用它把大量岗位砍到少数，再让第二层 LLM 只处理幸存者，控制成本。
"""
from models import SubRule, Job


def rule_matches_job(rule: SubRule, job: Job) -> bool:
    """岗位是否通过该订阅规则的硬条件。"""
    if rule.districts and job.district not in rule.districts:
        return False
    if rule.stages and job.stage not in rule.stages:
        return False
    if rule.subjects and job.subject not in rule.subjects:
        return False
    if rule.school_types:
        st = job.school_type.value if job.school_type else None
        if st not in rule.school_types:
            return False
    if rule.salary_floor and (job.salary_min or 0) < rule.salary_floor:
        return False
    if rule.need_establishment and not job.is_establishment:
        return False
    return True
