from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session

from database import Base, SessionLocal, engine
from models import Job, Resume, SubRule, Template, User, UserProfile


def content_hash(*parts: str) -> str:
    raw = "\n".join(parts)
    return sha256(raw.encode("utf-8")).hexdigest()


def rule_matches_job(rule: SubRule, job: Job) -> bool:
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


SEED_JOBS = [
    ("SZEDU", "南山区实验学校", "南山区", "小学", "语文", True, 2, 15000, 23000, "班主任经验优先，普通话二甲及以上。"),
    ("SZEDU", "深圳湾学校", "南山区", "初中", "数学", True, 1, 17000, 26000, "熟悉新课标，有竞赛辅导经验优先。"),
    ("SZEDU", "育才中学", "南山区", "高中", "英语", True, 1, 18000, 28000, "英语专业八级，能承担高中英语教学。"),
    ("FTEDU", "福田外国语小学", "福田区", "小学", "英语", False, 3, 13000, 21000, "具备小学英语教学经验，擅长课堂活动设计。"),
    ("FTEDU", "红岭教育集团", "福田区", "高中", "物理", True, 2, 19000, 30000, "有高三毕业班教学经验优先。"),
    ("FTEDU", "莲花中学", "福田区", "初中", "语文", False, 1, 14000, 22000, "热爱阅读推广，能承担社团指导。"),
    ("LHUEDU", "翠园东晓中学", "罗湖区", "初中", "化学", True, 1, 16000, 25000, "实验教学能力强，安全意识好。"),
    ("LHUEDU", "螺岭外国语实验学校", "罗湖区", "小学", "数学", False, 2, 12000, 20000, "低年段教学经验优先。"),
    ("BAOEDU", "宝安中学集团", "宝安区", "高中", "体育", True, 1, 17000, 27000, "足球或田径专项，能组织校队训练。"),
    ("BAOEDU", "新安湖小学", "宝安区", "小学", "美术", False, 1, 11000, 18000, "擅长儿童创意美术与校园活动。"),
    ("LONGEDU", "龙岗外国语学校", "龙岗区", "初中", "英语", True, 2, 15000, 24000, "口语表达优秀，有班主任经历优先。"),
    ("LONGEDU", "平湖实验学校", "龙岗区", "小学", "体育", False, 2, 12000, 19000, "篮球专项优先，能承担课后服务。"),
]


def seed_user(db: Session) -> User:
    user = db.scalar(select(User).where(User.openid == "demo-openid"))
    if user:
        return user

    user = User(openid="demo-openid", nickname="演示用户", phone="13800000000")
    db.add(user)
    db.flush()
    db.add(
        UserProfile(
            user_id=user.id,
            real_name="王老师",
            email="teacher@example.com",
            target_districts=["南山区", "宝安区"],
            target_stages=["小学", "初中"],
            target_subjects=["体育", "语文"],
            expected_salary_min=12000,
            expected_salary_max=26000,
            intro="深圳教师求职演示账号，关注公办学校体育与语文岗位。",
        )
    )
    db.add(
        Resume(
            user_id=user.id,
            name="深圳教师求职简历",
            file_url="https://example.com/resumes/demo-teacher.pdf",
            summary="2年体育教学经验，持有教师资格证，曾负责校队训练与班级管理。",
            is_default=True,
        )
    )
    db.add(
        Template(
            user_id=user.id,
            name="标准求职信",
            subject="应聘{school_name}{subject}教师岗位",
            body="尊敬的招聘负责人：您好！我希望应聘贵校{subject}教师岗位，期待进一步沟通。",
            is_default=True,
        )
    )
    db.add(
        SubRule(
            user_id=user.id,
            name="南山/宝安 体育或语文",
            districts=["南山区", "宝安区"],
            stages=["小学", "初中", "高中"],
            subjects=["体育", "语文"],
            salary_min=12000,
            salary_max=28000,
            require_bianzhi=False,
            active=True,
            threshold=75,
        )
    )
    return user


def seed_jobs(db: Session) -> None:
    now = datetime.now(UTC)
    for index, (source, school, district, stage, subject, bianzhi, headcount, salary_min, salary_max, extra) in enumerate(SEED_JOBS, start=1):
        external_id = f"{source}-{index:03d}"
        title = f"{school}{stage}{subject}教师招聘"
        jd = (
            f"{school}面向深圳招聘{stage}{subject}教师{headcount}名。"
            f"岗位位于{district}，薪资区间{salary_min}-{salary_max}元/月。{extra}"
        )
        existing = db.scalar(
            select(Job).where(Job.source == source, Job.external_id == external_id)
        )
        digest = content_hash(title, school, district, stage, subject, jd)
        if existing:
            existing.content_hash = digest
            existing.title = title
            existing.school_name = school
            existing.district = district
            existing.stage = stage
            existing.subject = subject
            existing.headcount = headcount
            existing.salary_min = salary_min
            existing.salary_max = salary_max
            existing.has_bianzhi = bianzhi
            existing.jd = jd
            continue
        db.add(
            Job(
                source=source,
                external_id=external_id,
                content_hash=digest,
                title=title,
                school_name=school,
                district=district,
                stage=stage,
                subject=subject,
                headcount=headcount,
                salary_min=salary_min,
                salary_max=salary_max,
                has_bianzhi=bianzhi,
                jd=jd,
                apply_email=f"hr{index}@example.edu.cn",
                source_url=f"https://example.edu.cn/jobs/{external_id}",
                published_at=now - timedelta(days=index),
                deadline_at=now + timedelta(days=30 - index),
            )
        )


def main() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_user(db)
        seed_jobs(db)
        db.commit()
    print("Seed complete: demo user and 12 jobs are ready.")


if __name__ == "__main__":
    main()
