import json

import services.resume_tailor as resume_tailor
from services.llm_credentials import LLMCredential

CRED = LLMCredential(api_key="sk-test-key", model="deepseek-chat")


def test_strip_fabricated_keys_removes_nested_extra_fields():
    original = {
        "basic": {"name": "李明", "education": "硕士"},
        "experience": [
            {"school": "A校", "role": "语文老师"},
            {"school": "B校", "role": "班主任"},
        ],
        "skills": ["普通话二甲", "语文教学"],
    }
    tailored = {
        "basic": {"name": "李明", "education": "硕士", "age": 28},
        "experience": [
            {"school": "A校", "role": "语文老师", "extra": "新增经历"},
            {"school": "B校", "role": "班主任"},
            {"school": "C校", "role": "新增岗位"},
        ],
        "skills": ["普通话二甲", "语文教学", "竞赛辅导"],
        "fabricated": "should drop",
    }

    cleaned = resume_tailor._strip_fabricated_keys(original, tailored)

    assert cleaned == {
        "basic": {"name": "李明", "education": "硕士"},
        "experience": [
            {"school": "A校", "role": "语文老师"},
            {"school": "B校", "role": "班主任"},
        ],
        "skills": ["普通话二甲", "语文教学"],
    }


def test_tailor_resume_strips_fabricated_keys_when_llm_returns_extra(monkeypatch):
    monkeypatch.setattr(resume_tailor.settings, "LLM_STUB_MODE", False)

    fake_payload = {
        "tailored_content": {
            "basic": {"name": "李明", "education": "硕士", "fabricated": "drop"},
            "experience": [{"school": "A校", "role": "语文老师", "extra": "drop"}],
            "new_section": ["drop"],
        },
        "change_summary": ["前置语文教学经历"],
    }

    monkeypatch.setattr(
        resume_tailor,
        "_call_deepseek",
        lambda system, user, **kw: json.dumps(fake_payload, ensure_ascii=False),
    )

    result = resume_tailor.tailor_resume(
        {
            "basic": {"name": "李明", "education": "硕士"},
            "experience": [{"school": "A校", "role": "语文老师"}],
        },
        "小学语文教师岗位",
        cred=CRED,
    )

    assert result["tailored_content"] == {
        "basic": {"name": "李明", "education": "硕士"},
        "experience": [{"school": "A校", "role": "语文老师"}],
    }
    assert "前置语文教学经历" in result["change_summary"]
