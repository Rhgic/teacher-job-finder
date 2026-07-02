from models import Job, SubRule


def rule_matches_job(rule: SubRule, job: Job) -> bool:
    if not rule.active:
        return False
    if rule.districts and job.district not in rule.districts:
        return False
    if rule.stages and job.stage not in rule.stages:
        return False
    if rule.subjects and job.subject not in rule.subjects:
        return False
    if rule.require_bianzhi and not job.has_bianzhi:
        return False
    if rule.salary_min is not None and job.salary_max is not None:
        if job.salary_max < rule.salary_min:
            return False
    if rule.salary_max is not None and job.salary_min is not None:
        if job.salary_min > rule.salary_max:
            return False
    return True
