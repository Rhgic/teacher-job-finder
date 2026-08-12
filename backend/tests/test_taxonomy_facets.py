"""筛选器分面接口。

背景：岗位页的学科按钮一度是写死在 HTML 里的 7 个，结果库里 7 个体育岗位、
3 个历史岗位在界面上根本点不到——数据、接口、爬虫全是好的，只是没人给
它们做按钮。这类 bug 不会让任何测试变红，只会让用户以为"平台没有这类岗位"。

所以这里守住三件事：
1. 标准表里的每个学科都出现在分面里（哪怕 count=0，前端置灰仍可见）。
2. 计数口径与 /jobs 列表一致，否则 chip 上写 6 点进去是 7。
3. 库里存在但标准表没有的值也要露出来，不能变成点不到的孤儿。
"""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import get_db
from main import app
from models import Base, Job
from services import taxonomy


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'facets.db'}", future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@pytest.fixture
def client(session_factory):
    def override():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def seeded_jobs(session_factory):
    future = date.today() + timedelta(days=30)
    past = date.today() - timedelta(days=1)
    db = session_factory()
    try:
        db.add_all([
            Job(school_name="A校", subject="体育", stage="小学", district="南山区", deadline=future),
            Job(school_name="B校", subject="体育", stage="初中", district="南山区", deadline=future),
            Job(school_name="C校", subject="体育", stage="初中", district="南山区", deadline=past),
            Job(school_name="D校", subject="语文", stage="小学", district="福田区", deadline=None),
            # 旧写法：库里是"心理"，标准表已改叫"心理健康"
            Job(school_name="E校", subject="心理", stage="高中", district="福田区", deadline=future),
            # 学科未识别
            Job(school_name="F校", subject=None, stage="小学", district="福田区", deadline=future),
        ])
        db.commit()
    finally:
        db.close()


def _by_value(items):
    return {i["value"]: i["count"] for i in items}


def test_every_standard_subject_appears(client, seeded_jobs):
    """标准表里的学科一个都不能少——少一个就是一批岗位点不到。"""
    subjects = _by_value(client.get("/taxonomy/facets").json()["subjects"])
    missing = [s for s in taxonomy.SUBJECTS if s not in subjects]
    assert not missing, f"这些学科没出现在筛选器里：{missing}"


def test_counts_exclude_expired_by_default(client, seeded_jobs):
    """计数必须与 /jobs 的默认口径一致。

    体育有 3 个岗位，其中 1 个已截止。chip 上应显示 2，
    否则用户点进去看到的条数和按钮上的数字对不上。
    """
    facets = client.get("/taxonomy/facets").json()
    assert _by_value(facets["subjects"])["体育"] == 2

    listed = client.get("/jobs?subject=体育&size=100").json()
    assert len(listed) == 2, "列表与计数口径不一致"


def test_include_expired_widens_both(client, seeded_jobs):
    facets = client.get("/taxonomy/facets?include_expired=true").json()
    assert _by_value(facets["subjects"])["体育"] == 3


def test_legacy_subject_name_is_merged_not_duplicated(client, seeded_jobs):
    """库里存"心理"、标准表叫"心理健康"，不能显示成两个 chip。"""
    subjects = _by_value(client.get("/taxonomy/facets").json()["subjects"])
    assert subjects["心理健康"] == 1
    assert "心理" not in subjects, "旧写法与标准名同时出现，用户会看到两个同义 chip"


def test_filtering_by_canonical_name_finds_legacy_rows(client, seeded_jobs):
    """点"心理健康"要能查到库里存为"心理"的岗位，否则 chip 写着 1 点进去是 0。"""
    listed = client.get("/jobs?subject=心理健康&size=100").json()
    assert len(listed) == 1
    assert listed[0]["school_name"] == "E校"


def test_unclassified_count_is_surfaced(client, seeded_jobs):
    """学科未识别的岗位数要单独露出来。

    它是爬虫质量问题，不是"没有这类岗位"——藏起来就没人会去修。
    """
    assert client.get("/taxonomy/facets").json()["unclassified_subject"] == 1


def test_values_present_in_data_but_not_in_taxonomy_still_listed(client, session_factory):
    """库里出现标准表没有的学科时，也要列出来，否则那些岗位同样点不到。"""
    db = session_factory()
    try:
        db.add(Job(school_name="G校", subject="书法", stage="小学",
                   district="南山区", deadline=date.today() + timedelta(days=10)))
        db.commit()
    finally:
        db.close()

    subjects = _by_value(client.get("/taxonomy/facets").json()["subjects"])
    assert subjects.get("书法") == 1
