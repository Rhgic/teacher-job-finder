from models import Job, SchoolType, SubRule
from services.rule_filter import rule_matches_job


def make_rule(**overrides):
    data = {
        "user_id": "user-1",
        "name": "南山小学语文编制",
        "districts": ["南山区"],
        "stages": ["小学"],
        "subjects": ["语文"],
        "school_types": ["public"],
        "salary_floor": 12000,
        "need_establishment": True,
    }
    data.update(overrides)
    return SubRule(**data)


def make_job(**overrides):
    data = {
        "school_name": "南山实验学校",
        "school_type": SchoolType.PUBLIC,
        "district": "南山区",
        "stage": "小学",
        "subject": "语文",
        "is_establishment": True,
        "salary_min": 15000,
    }
    data.update(overrides)
    return Job(**data)


def test_rule_matches_job_passes_when_hard_conditions_align():
    assert rule_matches_job(make_rule(), make_job()) is True


def test_rule_matches_job_rejects_mismatched_district():
    assert rule_matches_job(make_rule(), make_job(district="宝安区")) is False


def test_rule_matches_job_rejects_mismatched_school_type():
    assert rule_matches_job(make_rule(), make_job(school_type=SchoolType.PRIVATE)) is False


def test_rule_matches_job_rejects_salary_and_establishment():
    assert rule_matches_job(
        make_rule(),
        make_job(salary_min=10000, is_establishment=False),
    ) is False
