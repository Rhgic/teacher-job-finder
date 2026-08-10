"""
种子数据脚本。

运行:  python seed.py
作用:  建表 + 插入 1 个示例用户（含资料/简历/模板/一条订阅规则）
       + 12 条深圳教师岗位样本，并跑一遍"第一层规则过滤"生成匹配结果。

这样在爬虫还没动工前，整条链路（API → 前端卡片 → 规则过滤 → 待 LLM 评分）
就有真实数据可跑、可演示。爬虫做好后，只需把岗位来源从这里换成自动抓取，
下游一行都不用改。

注意: 样本里的 recruiter_email 全部用 example.edu.cn 占位，非真实邮箱。
"""
import hashlib
from datetime import date

from database import engine, SessionLocal, init_db
from models import (
    Base, User, UserProfile, Resume, Template, Job, SubRule, SchoolType,
)


def job_hash(school_name: str, subject: str | None, stage: str | None) -> str:
    """对岗位关键字段算指纹，用于去重 / 识别内容更新。"""
    raw = f"{school_name}|{subject or ''}|{stage or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


# 12 条深圳教师岗位样本（覆盖不同区/学段/学科/公办民办/编制）
SAMPLE_JOBS = [
    dict(school_name="南山区第二实验学校", school_type=SchoolType.PUBLIC, district="南山区",
         stage="小学", subject="语文", is_establishment=True, salary_min=15000, salary_max=22000),
    dict(school_name="深圳实验学校（福田部）", school_type=SchoolType.PUBLIC, district="福田区",
         stage="初中", subject="数学", is_establishment=True, salary_min=18000, salary_max=28000),
    dict(school_name="南山外国语学校", school_type=SchoolType.PUBLIC, district="南山区",
         stage="小学", subject="英语", is_establishment=False, salary_min=13000, salary_max=18000),
    dict(school_name="深圳中学龙岗学校", school_type=SchoolType.PUBLIC, district="龙岗区",
         stage="高中", subject="物理", is_establishment=True, salary_min=20000, salary_max=32000),
    dict(school_name="宝安区西乡小学", school_type=SchoolType.PUBLIC, district="宝安区",
         stage="小学", subject="数学", is_establishment=True, salary_min=14000, salary_max=20000),
    dict(school_name="深圳百合外国语学校", school_type=SchoolType.PRIVATE, district="龙岗区",
         stage="初中", subject="英语", is_establishment=False, salary_min=16000, salary_max=26000),
    dict(school_name="南山区荔湾小学", school_type=SchoolType.PUBLIC, district="南山区",
         stage="小学", subject="语文", is_establishment=False, salary_min=12000, salary_max=17000),
    dict(school_name="罗湖区翠竹外国语实验学校", school_type=SchoolType.PUBLIC, district="罗湖区",
         stage="小学", subject="美术", is_establishment=True, salary_min=13000, salary_max=19000),
    dict(school_name="龙华区第三实验学校", school_type=SchoolType.PUBLIC, district="龙华区",
         stage="初中", subject="化学", is_establishment=True, salary_min=16000, salary_max=24000),
    dict(school_name="深圳高级中学（南山）", school_type=SchoolType.PUBLIC, district="南山区",
         stage="高中", subject="语文", is_establishment=True, salary_min=22000, salary_max=35000),
    dict(school_name="坪山区同心外国语学校", school_type=SchoolType.PRIVATE, district="坪山区",
         stage="小学", subject="信息技术", is_establishment=False, salary_min=11000, salary_max=15000),
    dict(school_name="光明区凤凰学校", school_type=SchoolType.PUBLIC, district="光明区",
         stage="小学", subject="语文", is_establishment=True, salary_min=14000, salary_max=21000),
]


def rule_matches_job(rule: SubRule, job: Job) -> bool:
    """第一层：纯规则硬筛（毫秒级、确定性）。LLM 评分是之后的第二层。"""
    if rule.districts and job.district not in rule.districts:
        return False
    if rule.stages and job.stage not in rule.stages:
        return False
    if rule.subjects and job.subject not in rule.subjects:
        return False
    if rule.school_types and (job.school_type.value if job.school_type else None) not in rule.school_types:
        return False
    if rule.salary_floor and (job.salary_min or 0) < rule.salary_floor:
        return False
    if rule.need_establishment and not job.is_establishment:
        return False
    return True


def seed() -> None:
    # 全新开始：先清表再建表（开发期方便反复跑）
    Base.metadata.drop_all(bind=engine)
    init_db()

    db = SessionLocal()
    try:
        # --- 1. 示例用户 + 资料 + 简历 + 模板 ---
        user = User(openid="demo_openid_0001", nickname="求职中的小李")
        user.profile = UserProfile(
            real_name="李明", phone="13800000000", email="liming@example.com",
            education="硕士", major="汉语言文学", subject="语文", cert_no="20231100000000",
            intent={"districts": ["南山区", "福田区"], "stages": ["小学"], "establishment": True},
        )
        user.resumes.append(
            Resume(file_name="李明_语文教师_简历.pdf",
                   file_url="https://cos.example.com/resumes/liming_v1.pdf",
                   file_size=204800, is_default=True)
        )
        user.templates.append(
            Template(title="语文教师求职信", type="cover_letter",
                     content="尊敬的{school_name}招聘负责人：\n您好，我对贵校{subject}教师岗位很感兴趣……")
        )

        # --- 2. 一条订阅规则：南山/福田 · 小学语文 · 编制 ---
        rule = SubRule(
            name="南山福田·小学语文·编制",
            districts=["南山区", "福田区"], stages=["小学"], subjects=["语文"],
            school_types=None, salary_floor=12000, need_establishment=True,
            llm_threshold=70, is_active=True,
        )
        user.rules.append(rule)

        db.add(user)
        db.flush()  # 拿到 user.id / rule.id

        # --- 3. 插入岗位样本 ---
        jobs: list[Job] = []
        for i, data in enumerate(SAMPLE_JOBS, start=1):
            job = Job(
                source="seed",
                external_id=f"seed-{i:03d}",
                source_url=f"https://example.edu.cn/jobs/{i}",
                recruiter_email=f"hr{i:02d}@example.edu.cn",
                description=f"{data['school_name']}招聘{data['stage']}{data['subject']}教师，"
                            f"要求相关专业、持教师资格证。",
                # 截止日期设为未来：run_pipeline 会跳过 deadline<今天 的岗位，
                # 若仍是 2026-07-31（已过期），点"重新评分"会因全部被跳过而 0 new_matches，
                # 真实 LLM 分数永远不会出现。改未来日期后按钮才能真正触发评分。
                deadline=date(2026, 12, 31),
                content_hash=job_hash(data["school_name"], data["subject"], data["stage"]),
                **data,
            )
            jobs.append(job)
            db.add(job)
        db.commit()
        # 匹配结果（含真实 LLM 评分）不再在此预建：
        # run_pipeline 对已有 (rule,job) 是幂等跳过的，预建会让用户点"重新评分"时
        # 这些行被跳过、永远停在 llm_score=null，真实分数出不来。
        # 改为首刷时由 run_pipeline 实时生成。
        print(f"✅ 种子数据写入完成：1 个用户 · {len(jobs)} 个岗位 · 1 条订阅规则（评分待首次「重新评分」）")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
