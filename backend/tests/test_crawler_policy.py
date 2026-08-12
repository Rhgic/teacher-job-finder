"""爬虫的合规与数据质量闸门测试。

两条都是真实踩到的问题：
- robots.txt 返回 404 曾被当成"全站禁止"，把没有 robots.txt 的官方源整个屏蔽
- 官方公告栏里混着"拟录用公示""体检公告"，解析后是学校名为"广东省"的垃圾记录
"""
from urllib.robotparser import RobotFileParser

import pytest

from services.crawler import BaseCrawler, is_recruitment_posting


class _Resp:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


@pytest.fixture
def crawler():
    c = BaseCrawler()
    c._robots_cache = {}          # 类属性是共享字典，逐用例隔离
    return c


def _load_with(monkeypatch, crawler, resp):
    import httpx

    monkeypatch.setattr(httpx, "get", lambda *a, **k: resp)
    return crawler._load_robots("https://example.com")


def test_missing_robots_allows_crawling(monkeypatch, crawler):
    """404 表示站点没有 robots.txt，按 RFC 9309 应视为全部允许。"""
    parser = _load_with(monkeypatch, crawler, _Resp(404, "<html>Not Found</html>"))
    assert isinstance(parser, RobotFileParser)
    assert parser.can_fetch("TeacherJobBot/0.1", "https://example.com/jobs/1.html")


def test_forbidden_robots_blocks_crawling(monkeypatch, crawler):
    """401/403 是站点明确拒绝，按全站禁止处理。"""
    for status in (401, 403):
        assert _load_with(monkeypatch, crawler, _Resp(status)) is None


def test_server_error_blocks_crawling(monkeypatch, crawler):
    """5xx 站点状态不明，保守禁止而不是当作没有 robots。"""
    assert _load_with(monkeypatch, crawler, _Resp(503)) is None


def test_network_failure_blocks_crawling(monkeypatch, crawler):
    import httpx

    def boom(*a, **k):
        raise httpx.ConnectError("dns fail")

    monkeypatch.setattr(httpx, "get", boom)
    assert crawler._load_robots("https://example.com") is None


def test_robots_rules_are_honored(monkeypatch, crawler):
    """正常返回时仍按规则逐条判定，修复不能放松真实的 Disallow。"""
    body = "User-agent: *\nDisallow: /private/\n"
    parser = _load_with(monkeypatch, crawler, _Resp(200, body))
    assert parser.can_fetch("TeacherJobBot/0.1", "https://example.com/jobs/1.html")
    assert not parser.can_fetch("TeacherJobBot/0.1", "https://example.com/private/x.html")


@pytest.mark.parametrize("title", [
    "深圳市公办中小学2026年6月公开招聘教师公告",
    "深圳中学高中园2026年7月面向2026年应届毕业生招聘教师",
    "深圳外国语学校高中园2026年6月面向2026年应届毕业生公开招聘",
])
def test_real_postings_are_kept(title):
    """真实招聘同样以"公告"结尾，不能拿"公告"当过滤依据。"""
    assert is_recruitment_posting(title)


@pytest.mark.parametrize("title", [
    "广东省2026年考试录用公务员深圳市教育局拟录用人员公示公告",
    "广东省2026年度选调优秀大学毕业生深圳市教育局拟录用人员公示公告",
    "广东省2026年考试录用公务员、2026年度选调优秀大学毕业生深圳市教育局职位体检公告",
    "深圳市教育局2025年面向市内公开选调公务员拟选调人员公示公告",
])
def test_process_results_are_filtered(title):
    """流程结果与公务员招录都不是可投递的教师岗位。"""
    assert not is_recruitment_posting(title)


def test_empty_title_is_filtered():
    assert not is_recruitment_posting("")
    assert not is_recruitment_posting("   ")


@pytest.mark.parametrize("text,expected", [
    # 标题里的区应压过正文里顺带提到的区
    ("深汕合作区公办幼儿园招聘，办公地址龙岗区某路", "深汕特别合作区"),
    ("深汕特别合作区四所公办幼儿园", "深汕特别合作区"),
    ("龙岗区中心城某公办学校招聘语文教师", "龙岗区"),
    ("深圳外国语学校（福田区）招聘", "福田区"),
    ("无区域信息的公告", None),
])
def test_district_prefers_earliest_mention(text, expected):
    """按出现位置取最靠前的区，而非标准表里的排列顺序。"""
    from services.crawler import _guess_district

    assert _guess_district(text) == expected


def test_empty_crawl_is_reported_not_silent(monkeypatch, tmp_path, caplog):
    """抓到 0 条必须记 ERROR。

    这些站点是 HTML 解析，改版后爬虫会静默返回空、定时任务照常"成功"退出，
    数据悄悄停止增长而没有任何信号——静默失败比崩溃更难发现。
    """
    import logging

    from scripts import run_scheduled_crawl as job

    class EmptyCrawler:
        source = "fake"
        obey_robots = True
        min_interval_sec = 2.0
        cache_ttl_sec = 1800
        max_detail_pages = 10

        def fetch(self):
            return []

    monkeypatch.setattr(job, "CRAWLERS", {"fake": EmptyCrawler})
    monkeypatch.setattr(job, "init_db", lambda: None)
    monkeypatch.setattr(job, "upsert_jobs", lambda db, raws: {"new": 0, "updated": 0})

    class _NullSession:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(job, "SessionLocal", _NullSession)

    args = job.parse_args(["--source", "fake", "--no-match"])
    with caplog.at_level(logging.ERROR):
        result = job.run_once(args)

    assert result["empty_sources"] == ["fake"]
    assert "crawl_returned_nothing" in caplog.text


# --------------------------------------------------------------------------- #
# 正文级复检：标题过闸后，正文仍可能暴露这不是招聘公告                             #
# --------------------------------------------------------------------------- #

def test_body_check_rejects_result_announcements():
    """标题里"公开招聘教师"字样俱全，只有正文才看得出是在公布成绩。"""
    from services.crawler import is_recruitment_body

    cases = [
        ("深圳市龙岗区第二外国语学校",
         "深圳市龙岗区第二外国语学校（集团）2026年上半年赴北京面向2026年应届毕业生"
         "公开招聘教师面试工作已结束。现将总成绩及入围体检人员名单予以公布"),
        ("深圳市第七高级中学",
         "经体检、考察等程序合格，现将深圳市公办中小学公开招聘教师拟聘人员名单予以公示"),
        ("深圳市龙岗区教育局",
         "深圳市龙岗区教育局2026年上半年公开招聘教师资格复审工作已于5月26日结束"),
    ]
    for name, desc in cases:
        assert not is_recruitment_body(name, desc), f"没拦住：{name}"


def test_body_check_rejects_commercial_ads():
    """教师求职站点上混着机构转让、加盟这类帖子。"""
    from services.crawler import is_recruitment_body

    assert not is_recruitment_body(
        "龙华艺术机构转让",
        "龙华有家艺术机构，证件齐全。目前课消每月15万左右，主理人出国想转让",
    )


def test_body_check_keeps_real_postings_with_similar_words():
    """**这条是重点**：真实招聘公告的表格里就有"拟聘岗位""拟聘人数"这类表头。

    只按"拟聘"两个字过滤，会把下面这两条真岗位一起杀掉——
    所以判据必须是短语，不能是孤立关键词。
    """
    from services.crawler import is_recruitment_body

    keepers = [
        ("招10人！深圳市光明区中等职业技术学校",
         "深圳市光明区中等职业技术学校，是隶属于光明区教育局的公办中职学校。"
         "因办学需要，现面向社会公开招聘教师，拟聘岗位及人数如下"),
        ("深圳中学大鹏学校",
         "深圳中学大鹏学校2026年6月面向社会人员公开招聘教师 一、招聘岗位及相关要求："
         "初中语文1名、初中数学2名、初中英语1名 岗位名称 拟聘 人数"),
    ]
    for name, desc in keepers:
        assert is_recruitment_body(name, desc), f"误伤了真岗位：{name}"


def test_body_check_only_looks_at_the_head():
    """只检查开头一段。

    真实招聘公告的正文后半段常引用往届公示（"参见2025年拟聘人员名单"），
    全文扫描会把它们误判成结果公告。
    """
    from services.crawler import is_recruitment_body

    desc = "现面向社会公开招聘初中数学教师2名。" + "岗位职责说明。" * 40 + "参见去年拟聘人员名单"
    assert is_recruitment_body("某中学", desc)


def test_upsert_rejects_and_reports_count():
    """入库处要拦下来，并把拦截数单独报出来。

    抓到 20 条入库 14 条时，要能一眼看出是源站没更新还是被过滤器拦了。
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from models import Base
    from services.crawler import RawJob, upsert_jobs

    engine = create_engine("sqlite://", future=True,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()
    try:
        stats = upsert_jobs(db, [
            RawJob(source="t", external_id="1", source_url="u1",
                   school_name="真岗位中学", description="现面向社会公开招聘初中数学教师2名"),
            RawJob(source="t", external_id="2", source_url="u2",
                   school_name="某中学", description="经体检、考察等程序合格，现将拟聘人员名单予以公示"),
        ])
        assert stats["new"] == 1
        assert stats["rejected"] == 1
    finally:
        db.close()
