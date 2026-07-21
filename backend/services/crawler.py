"""爬虫（最后做，见方案阶段 6）。

框架给出统一接口与入库去重逻辑。Codex 要填的是各站点的具体解析，
并守住合规：优先官方公告源、遵守 robots、限速、缓存。
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from datetime import date
from dataclasses import dataclass, asdict
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

from sqlalchemy import select
from sqlalchemy.orm import Session

from services import taxonomy

from models import Job, SchoolType


@dataclass
class RawJob:
    """各爬虫统一产出的中间结构，再由 upsert 入库。"""
    source: str
    external_id: str
    source_url: str
    school_name: str
    school_type: SchoolType | None = None
    district: str | None = None
    stage: str | None = None
    subject: str | None = None
    is_establishment: bool | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    recruiter_email: str | None = None
    description: str | None = None
    deadline: date | None = None


# 招聘流程中的结果类公告，以及公务员招录——都不是可投递的教师岗位。
# 注意不能用"公告"做判据：真实招聘标题同样以"公告"结尾
#（如"深圳市公办中小学2026年6月公开招聘教师公告"）。
NON_POSTING_MARKERS = (
    "拟录用", "拟聘用", "拟聘", "拟选调", "公示",
    "体检公告", "考察结果", "成绩公布", "面试名单", "递补",
    "公务员", "选调生",
)


def is_recruitment_posting(title: str) -> bool:
    """判断列表页标题是否为可投递的招聘公告。

    官方公告栏里混着大量"拟录用人员公示""体检公告"这类流程结果，
    解析它们会得到学校名是"广东省"、学科靠关键词误命中的垃圾记录，
    入库后直接污染岗位列表，因此在链接阶段就滤掉。
    """
    text = (title or "").strip()
    if not text:
        return False
    return not any(marker in text for marker in NON_POSTING_MARKERS)


def content_hash(r: RawJob) -> str:
    raw = f"{r.school_name}|{r.subject or ''}|{r.stage or ''}|{r.description or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def upsert_jobs(db: Session, raws: list[RawJob]) -> dict:
    """按 (source, external_id) 去重入库；content_hash 变化则更新。已实现。"""
    new, updated = 0, 0
    for r in raws:
        existing = db.scalar(
            select(Job).where(Job.source == r.source, Job.external_id == r.external_id)
        )
        h = content_hash(r)
        if existing is None:
            db.add(Job(content_hash=h, **asdict(r)))
            new += 1
        elif existing.content_hash != h or any(
            getattr(existing, k) != v for k, v in asdict(r).items()
        ):
            for k, v in asdict(r).items():
                setattr(existing, k, v)
            existing.content_hash = h
            updated += 1
    db.commit()
    return {"new": new, "updated": updated}


class BaseCrawler:
    """各站点爬虫基类。

    子类只需实现 fetch()，把页面解析成 RawJob 列表。
    合规：请用 polite_get 发请求（自带 UA 与限速），并先检查目标站 robots。
    """
    source: str = "base"
    min_interval_sec: float = 2.0  # 两次请求最小间隔，礼貌限速
    cache_ttl_sec: int = 1800
    cache_dir: Path = Path(os.getenv("CRAWLER_CACHE_DIR", ".crawler_cache"))
    obey_robots: bool = os.getenv("CRAWLER_OBEY_ROBOTS", "1") != "0"
    _last_ts: float = 0.0
    _robots_cache: dict[str, RobotFileParser | None] = {}

    def polite_get(self, url: str, **kwargs):
        """限速 + robots + 简单文件缓存 + 带 UA 的 GET。子类抓取时统一用它。"""
        import httpx

        if self.obey_robots and not self._allowed_by_robots(url, **kwargs):
            raise PermissionError(f"robots disallow: {url}")

        cache_key = self._cache_key(url)
        cached = self._read_cache(cache_key)
        if cached is not None:
            return _CachedResponse(cached)

        wait = self.min_interval_sec - (time.monotonic() - self._last_ts)
        if wait > 0:
            time.sleep(wait)
        headers = {"User-Agent": "TeacherJobBot/0.1 (+contact)"}
        headers.update(kwargs.pop("headers", {}))
        resp = httpx.get(url, headers=headers, timeout=30, follow_redirects=True, **kwargs)
        self._last_ts = time.monotonic()
        resp.raise_for_status()
        self._write_cache(cache_key, resp.content)
        return resp

    def _allowed_by_robots(self, url: str, **kwargs) -> bool:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return False
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._robots_cache:
            self._robots_cache[origin] = self._load_robots(origin, **kwargs)
        robots = self._robots_cache[origin]
        if robots is None:
            return False
        return robots.can_fetch("TeacherJobBot/0.1", url)

    def _load_robots(self, origin: str, **kwargs) -> RobotFileParser | None:
        """取站点 robots.txt。返回 None 表示"按禁止处理"。

        状态码按 RFC 9309 §2.3.1 区分，不能一律当作禁止：
        - 401/403：站点明确拒绝访问 robots 本身 → 全站禁止
        - 其它 4xx（含 404）：站点没有 robots.txt → 全部允许。
          曾把 404 一并当成禁止，结果把没有 robots.txt 的官方公告源
          整个屏蔽掉了，白白丢失最权威的数据来源。
        - 5xx / 网络异常：站点状态不明 → 保守按禁止处理
        """
        import httpx

        robots_url = f"{origin}/robots.txt"
        headers = {"User-Agent": "TeacherJobBot/0.1 (+contact)"}
        headers.update(kwargs.pop("headers", {}))
        try:
            resp = httpx.get(
                robots_url,
                headers=headers,
                timeout=10,
                follow_redirects=True,
                **kwargs,
            )
        except Exception:
            return None

        parser = RobotFileParser()
        parser.set_url(robots_url)
        if resp.status_code in (401, 403):
            return None
        if resp.status_code >= 500:
            return None
        if resp.status_code >= 400:
            parser.allow_all = True
            return parser
        parser.parse(resp.text.splitlines())
        return parser

    def _cache_key(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.cache_dir / self.source / f"{digest}.bin"

    def _read_cache(self, path: Path) -> bytes | None:
        if self.cache_ttl_sec <= 0 or not path.exists():
            return None
        if time.time() - path.stat().st_mtime > self.cache_ttl_sec:
            return None
        return path.read_bytes()

    def _write_cache(self, path: Path, content: bytes) -> None:
        if self.cache_ttl_sec <= 0:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def fetch(self) -> list[RawJob]:
        """抓取并解析为 RawJob 列表。

        TODO(codex)：子类实现。务必遵守 robots、限速、缓存；优先官方公告源。
        """
        raise NotImplementedError


class _CachedResponse:
    def __init__(self, content: bytes):
        self.content = content

    @property
    def text(self) -> str:
        return _decode_html(self.content)


class ShenzhenEduBureauCrawler(BaseCrawler):
    """示例：深圳市/区教育局公告源。Codex 填具体抓取与字段解析。"""
    source = "sz_edu_bureau"
    base_url = "https://szeb.sz.gov.cn"
    list_urls = (
        "https://szeb.sz.gov.cn/home/xxgk/flzy/rsxx2/ryzp/index.html",
        "https://szeb.sz.gov.cn/home/xxgk/flzy/rsxx2/ryzp/index_14.html",
    )
    max_detail_pages = int(os.getenv("CRAWL_MAX_DETAIL_PAGES", "40"))

    def fetch(self) -> list[RawJob]:
        """抓取深圳市教育局「人员招聘」公告并解析为 RawJob。

        只对接一个官方源；列表页结构变化时返回已能解析的结果，不让调用方崩溃。
        由于该站部分环境 TLS/证书链不稳定，verify=False 仅用于本官方源抓取，
        同时仍通过 polite_get 保持 UA、限速与 follow_redirects。
        """
        detail_links = self._fetch_detail_links()
        raws: list[RawJob] = []
        for url, title in detail_links[: self.max_detail_pages]:
            try:
                resp = self.polite_get(url, verify=False)
            except Exception:
                continue
            text = _html_to_text(resp.text)
            raw = self._parse_detail(url, title, text)
            if raw:
                raws.append(raw)
        return raws

    def _fetch_detail_links(self) -> list[tuple[str, str]]:
        links: list[tuple[str, str]] = []
        seen: set[str] = set()
        list_urls = tuple(
            url.strip()
            for url in os.getenv("SZEB_RYZP_LIST_URLS", "").split(",")
            if url.strip()
        ) or self.list_urls
        for list_url in list_urls:
            try:
                resp = self.polite_get(list_url, verify=False)
            except Exception:
                continue
            for href, title in _extract_links(resp.text, list_url):
                if "/ryzp/content/post_" not in href or href in seen:
                    continue
                seen.add(href)
                if not is_recruitment_posting(title):
                    continue
                links.append((href, title))
        return links

    def _parse_detail(self, url: str, title: str, text: str) -> RawJob | None:
        external_id_match = re.search(r"post_(\d+)\.html", url)
        external_id = (
            external_id_match.group(1)
            if external_id_match
            else hashlib.sha1(url.encode()).hexdigest()[:16]
        )
        title = title or _extract_title_from_text(text)
        if not title:
            return None

        description = _compact_text(text)
        district = _guess_district(title + "\n" + description)
        stage = _guess_stage(title + "\n" + description)
        subject = _guess_subject(title + "\n" + description)
        school_name = _guess_school_name(title)
        email = _guess_email(description)
        is_establishment = (
            True
            if ("公办" in title or "事业单位" in description or "编制" in description)
            else None
        )

        return RawJob(
            source=self.source,
            external_id=external_id,
            source_url=url,
            school_name=school_name,
            school_type=SchoolType.PUBLIC if is_establishment else None,
            district=district,
            stage=stage,
            subject=subject,
            is_establishment=is_establishment,
            recruiter_email=email,
            description=description,
            deadline=_guess_deadline(description),
        )


class ShenzhenTeacherTalentCrawler(BaseCrawler):
    """深圳教师人才网（sz910.cn）本地招聘源。

    只抓招聘/招考详情页，避开简历库等求职者个人信息页面。
    """
    source = "sz910"
    base_url = "https://www.sz910.cn"
    list_urls = ("https://www.sz910.cn/",)
    max_detail_pages = int(os.getenv("CRAWL_MAX_DETAIL_PAGES", "40"))

    allowed_prefixes = (
        "/zhanwuzhongxin/zhaokao/",
        "/gongbanxuexiao/",
        "/mingbanxuexiao/",
        "/youeryuan/",
        "/peixunjigou/",
    )

    def fetch(self) -> list[RawJob]:
        detail_links = self._fetch_detail_links()
        raws: list[RawJob] = []
        for url, title in detail_links[: self.max_detail_pages]:
            try:
                resp = self.polite_get(url)
            except Exception:
                continue
            html = _decode_html(resp.content)
            raw = self._parse_detail(url, title, html)
            if raw:
                raws.append(raw)
        return raws

    def _fetch_detail_links(self) -> list[tuple[str, str]]:
        links: list[tuple[str, str]] = []
        seen: set[str] = set()
        list_urls = tuple(
            url.strip()
            for url in os.getenv("SZ910_LIST_URLS", "").split(",")
            if url.strip()
        ) or self.list_urls
        for list_url in list_urls:
            try:
                resp = self.polite_get(list_url)
            except Exception:
                continue
            html = _decode_html(resp.content)
            for href, title in _extract_links(html, list_url):
                if href in seen or not self._is_allowed_detail_url(href):
                    continue
                seen.add(href)
                if not is_recruitment_posting(title):
                    continue
                links.append((href, title))
        return links

    def _is_allowed_detail_url(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.netloc and parsed.netloc not in {"www.sz910.cn", "sz910.cn"}:
            return False
        path = parsed.path
        if not path.endswith(".html"):
            return False
        if not any(path.startswith(prefix) for prefix in self.allowed_prefixes):
            return False
        # robots 允许这些栏目；这里额外避开求职简历、会员、后台等个人信息或系统页。
        blocked_parts = ("/jianli/", "/d/", "/e/", "/about/")
        return not any(part in path for part in blocked_parts)

    def _parse_detail(self, url: str, list_title: str, html: str) -> RawJob | None:
        title = _extract_h1(html) or list_title or _extract_title_from_text(_html_to_text(html))
        if not title:
            return None

        body_html = _extract_element_by_id(html, "text") or html
        description = _compact_text(_html_to_text(body_html))
        if not description:
            return None

        path = urlparse(url).path
        external_id_match = re.search(r"/(\d+)\.html$", path)
        external_id = (
            external_id_match.group(1)
            if external_id_match
            else hashlib.sha1(url.encode()).hexdigest()[:16]
        )
        combined = title + "\n" + description + "\n" + path
        school_type = self._guess_school_type(path, combined)
        is_establishment = self._guess_establishment(school_type, combined)

        return RawJob(
            source=self.source,
            external_id=external_id,
            source_url=url,
            school_name=_guess_school_name(title),
            school_type=school_type,
            district=_guess_district(combined) or _guess_district_from_path(path),
            stage=_guess_stage(combined),
            subject=_guess_subject(combined),
            is_establishment=is_establishment,
            salary_min=_guess_salary_min(description),
            salary_max=_guess_salary_max(description),
            recruiter_email=_guess_email(description),
            description=description,
            deadline=_guess_deadline(description),
        )

    def _guess_school_type(self, path: str, text: str) -> SchoolType | None:
        if "/gongbanxuexiao/" in path or "公办" in text or "公立" in text:
            return SchoolType.PUBLIC
        if "/mingbanxuexiao/" in path or "/peixunjigou/" in path or "民办" in text:
            return SchoolType.PRIVATE
        return None

    def _guess_establishment(self, school_type: SchoolType | None, text: str) -> bool | None:
        if any(word in text for word in ("事业编制", "在编", "编制教师", "选调优秀教师")):
            return True
        if any(word in text for word in ("购买服务", "第三方", "劳务合同", "临聘", "顶岗", "实习")):
            return False
        if school_type == SchoolType.PRIVATE:
            return False
        return None


class ShenzhenTeacherRecruitCrawler(BaseCrawler):
    """深圳教师招聘网（shenzhenjiaoshi.com）本地招聘源。

    robots 当前允许 /zhaopin/；只抓招聘详情页，避开 /d/、/vip/ 等系统或个人信息路径。
    """
    source = "shenzhenjiaoshi"
    base_url = "https://www.shenzhenjiaoshi.com"
    list_urls = ("https://www.shenzhenjiaoshi.com/zhaopin/",)
    max_detail_pages = int(os.getenv("CRAWL_MAX_DETAIL_PAGES", "40"))

    def fetch(self) -> list[RawJob]:
        detail_links = self._fetch_detail_links()
        raws: list[RawJob] = []
        for url, title in detail_links[: self.max_detail_pages]:
            try:
                resp = self.polite_get(url)
            except Exception:
                continue
            html = _decode_html(resp.content)
            raw = self._parse_detail(url, title, html)
            if raw:
                raws.append(raw)
        return raws

    def _fetch_detail_links(self) -> list[tuple[str, str]]:
        links: list[tuple[str, str]] = []
        seen: set[str] = set()
        list_urls = tuple(
            url.strip()
            for url in os.getenv("SHENZHENJIAOSHI_LIST_URLS", "").split(",")
            if url.strip()
        ) or self.list_urls
        for list_url in list_urls:
            try:
                resp = self.polite_get(list_url)
            except Exception:
                continue
            html = _decode_html(resp.content)
            for href, title in _extract_links(html, list_url):
                if href in seen or not self._is_allowed_detail_url(href):
                    continue
                seen.add(href)
                if not is_recruitment_posting(title):
                    continue
                links.append((href, title))
        return links

    def _is_allowed_detail_url(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.netloc and parsed.netloc not in {"www.shenzhenjiaoshi.com", "shenzhenjiaoshi.com"}:
            return False
        path = parsed.path
        if not re.match(r"^/zhaopin/\d+\.html$", path):
            return False
        blocked_parts = ("/d/", "/vip/", "/e/", "/jianli/")
        return not any(part in path for part in blocked_parts)

    def _parse_detail(self, url: str, list_title: str, html: str) -> RawJob | None:
        title = _extract_h1(html) or list_title or _extract_title_from_text(_html_to_text(html))
        if not title:
            return None

        body_html = (
            _extract_shenzhenjiaoshi_body(html)
            or _extract_element_by_class(html, "zhengwen")
            or _extract_element_by_class(html, "left")
            or _extract_element_by_class(html, "article")
            or _extract_element_by_class(html, "content")
            or _extract_element_by_class(html, "newstext")
            or _extract_element_by_id(html, "text")
            or html
        )
        description = _compact_text(_html_to_text(body_html))
        if not description:
            return None

        path = urlparse(url).path
        external_id_match = re.search(r"/(\d+)\.html$", path)
        external_id = (
            external_id_match.group(1)
            if external_id_match
            else hashlib.sha1(url.encode()).hexdigest()[:16]
        )
        combined = title + "\n" + description
        school_type = self._guess_school_type(combined)
        is_establishment = self._guess_establishment(school_type, combined)

        return RawJob(
            source=self.source,
            external_id=external_id,
            source_url=url,
            school_name=_guess_school_name(title),
            school_type=school_type,
            district=_guess_district(title) or _guess_district(description),
            stage=_guess_stage(title) or _guess_stage(description),
            subject=_guess_subject(title) or _guess_subject(description),
            is_establishment=is_establishment,
            salary_min=_guess_salary_min(description),
            salary_max=_guess_salary_max(description),
            recruiter_email=_guess_email(description),
            description=description,
            deadline=_guess_deadline(description),
        )

    def _guess_school_type(self, text: str) -> SchoolType | None:
        if "公办" in text or "公立" in text or "教育局" in text:
            return SchoolType.PUBLIC
        if "民办" in text or "培训机构" in text or "机构招聘" in text:
            return SchoolType.PRIVATE
        return None

    def _guess_establishment(self, school_type: SchoolType | None, text: str) -> bool | None:
        if any(word in text for word in ("事业编制", "在编", "编制教师", "选聘")):
            return True
        if any(word in text for word in ("临聘", "编外", "购买服务", "实习", "兼职", "劳务合同")):
            return False
        if school_type == SchoolType.PRIVATE:
            return False
        return None


def _extract_links(html: str, base_url: str) -> list[tuple[str, str]]:
    links: list[tuple[str, str]] = []
    for match in re.finditer(
        r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>",
        html,
        flags=re.I | re.S,
    ):
        href = urljoin(base_url, unescape(match.group(1).strip()))
        title = _compact_text(_html_to_text(match.group(2)))
        if title:
            if not is_recruitment_posting(title):
                continue
            links.append((href, title))
    return links


def _decode_html(content: bytes) -> str:
    for encoding in ("utf-8", "gb18030", "gbk", "gb2312"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="ignore")


def _extract_h1(html: str) -> str:
    match = re.search(r"<h1\b[^>]*>(.*?)</h1>", html, flags=re.I | re.S)
    return _compact_text(_html_to_text(match.group(1))) if match else ""


def _extract_element_by_id(html: str, element_id: str) -> str:
    pattern = rf"<(?P<tag>[a-z0-9]+)\b[^>]*\bid=[\"']{re.escape(element_id)}[\"'][^>]*>(?P<body>.*?)</(?P=tag)>"
    match = re.search(pattern, html, flags=re.I | re.S)
    return match.group("body") if match else ""


def _extract_element_by_class(html: str, class_name: str) -> str:
    pattern = rf"<(?P<tag>[a-z0-9]+)\b[^>]*\bclass=[\"'][^\"']*\b{re.escape(class_name)}\b[^\"']*[\"'][^>]*>(?P<body>.*?)</(?P=tag)>"
    match = re.search(pattern, html, flags=re.I | re.S)
    return match.group("body") if match else ""


def _extract_shenzhenjiaoshi_body(html: str) -> str:
    start_match = re.search(r"<div\b[^>]*\bclass=[\"'][^\"']*\bzhengwen\b[^\"']*[\"'][^>]*>", html, flags=re.I)
    if not start_match:
        return ""
    start = start_match.end()
    end_candidates = []
    for marker in (r"<div\b[^>]*\bclass=[\"'][^\"']*\bright\b", r"<div\b[^>]*\bclass=[\"'][^\"']*\btuijian\b"):
        marker_match = re.search(marker, html[start:], flags=re.I)
        if marker_match:
            end_candidates.append(start + marker_match.start())
    end = min(end_candidates) if end_candidates else min(len(html), start + 40000)
    return html[start:end]


def _html_to_text(html: str) -> str:
    html = re.sub(r"<script\b.*?</script>", " ", html, flags=re.I | re.S)
    html = re.sub(r"<style\b.*?</style>", " ", html, flags=re.I | re.S)
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    html = re.sub(r"</p\s*>|</div\s*>|</li\s*>|</h\d\s*>", "\n", html, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", html)
    return unescape(text)


def _compact_text(text: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _extract_title_from_text(text: str) -> str:
    for line in _compact_text(text).splitlines():
        if "招聘" in line or "公告" in line or "公示" in line:
            return line
    return ""


def _guess_school_name(title: str) -> str:
    title = title.strip()
    patterns = [
        r"(.+?学校)",
        r"(.+?中学)",
        r"(.+?小学)",
        r"(.+?幼儿园)",
        r"(.+?教育集团)",
    ]
    for pattern in patterns:
        match = re.search(pattern, title)
        if match:
            return match.group(1)
    before_recruit = re.split(r"\d{4}年|公开招聘|面向|关于", title)[0].strip(" ，。")
    return before_recruit or title[:80]


def _guess_district(text: str) -> str | None:
    """从公告文本识别所属区。

    取"出现位置最靠前"的那个而非列表里的第一个：文本是标题+正文拼接，
    标题里的区才是岗位所在地，正文里顺带提到的区（办公地址、参照文件等）
    不该压过它。曾因按列表顺序匹配，把"深汕合作区公办幼儿园"错标成龙岗区。

    同时接受公告常用简称（如"深汕合作区"），归一到标准区名。
    """
    best: tuple[int, str] | None = None
    for alias, canonical in taxonomy.DISTRICT_ALIASES.items():
        pos = text.find(alias)
        if pos >= 0 and (best is None or pos < best[0]):
            best = (pos, canonical)
    for district in taxonomy.DISTRICTS:
        pos = text.find(district)
        if pos >= 0 and (best is None or pos < best[0]):
            best = (pos, district)
    return best[1] if best else None


def _guess_district_from_path(path: str) -> str | None:
    mapping = {
        "futian": "福田区",
        "luohu": "罗湖区",
        "nanshan": "南山区",
        "yantian": "盐田区",
        "baoan": "宝安区",
        "longgang": "龙岗区",
        "longhua": "龙华区",
        "pingshan": "坪山区",
        "guangming": "光明区",
        "dapeng": "大鹏新区",
    }
    for key, value in mapping.items():
        if f"/{key}/" in path:
            return value
    return None


def _guess_stage(text: str) -> str | None:
    if "幼儿园" in text or "学前" in text:
        return "幼儿园"
    if "小学" in text:
        return "小学"
    if "初中" in text:
        return "初中"
    if "高中" in text:
        return "高中"
    if "中职" in text or "职业技术" in text:
        return "中职"
    if "中小学" in text:
        return "中小学"
    return None


def _guess_subject(text: str) -> str | None:
    for subject in taxonomy.SUBJECTS:
        if subject in text:
            return subject
    return None


def _guess_email(text: str) -> str | None:
    match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    return match.group(0) if match else None


def _guess_salary_min(text: str) -> int | None:
    salary = _guess_salary_range(text)
    return salary[0] if salary else None


def _guess_salary_max(text: str) -> int | None:
    salary = _guess_salary_range(text)
    return salary[1] if salary else None


def _guess_salary_range(text: str) -> tuple[int | None, int | None] | None:
    text = text.replace("～", "~").replace("—", "-").replace("－", "-")
    salary_keywords = ("年薪", "月薪", "薪资", "薪酬", "工资", "待遇", "收入")
    windows: list[str] = []
    for keyword in salary_keywords:
        for match in re.finditer(keyword, text):
            start = max(0, match.start() - 20)
            end = min(len(text), match.end() + 80)
            windows.append(text[start:end])
    if not windows:
        return None
    search_text = "\n".join(windows)

    annual = re.search(r"年薪[：:\s]*([0-9]+(?:\.[0-9]+)?)\s*(?:万|w)\s*[~-]\s*([0-9]+(?:\.[0-9]+)?)\s*(?:万|w)", search_text, re.I)
    if annual:
        low = int(float(annual.group(1)) * 10000 / 12)
        high = int(float(annual.group(2)) * 10000 / 12)
        return low, high

    monthly = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*[kK]\s*[~-]\s*([0-9]+(?:\.[0-9]+)?)\s*[kK]?", search_text)
    if monthly:
        low = int(float(monthly.group(1)) * 1000)
        high = int(float(monthly.group(2)) * 1000)
        return low, high

    yuan = re.search(r"([0-9]{4,5})\s*[~-]\s*([0-9]{4,5})", search_text)
    if yuan:
        return int(yuan.group(1)), int(yuan.group(2))

    return None


def _guess_deadline(text: str) -> date | None:
    compact = _compact_text(text)
    if not compact:
        return None

    deadline_keywords = (
        "截止", "报名时间", "报名截止", "投递截止", "接收简历", "简历投递",
        "报名邮箱", "招聘邮箱", "请于", "发送至",
    )
    windows: list[str] = []
    for keyword in deadline_keywords:
        for match in re.finditer(keyword, compact):
            start = max(0, match.start() - 40)
            end = min(len(compact), match.end() + 120)
            windows.append(compact[start:end])
    search_text = "\n".join(windows) if windows else compact[:3000]

    explicit = re.findall(
        r"(20\d{2})\s*[年./-]\s*(\d{1,2})\s*[月./-]\s*(\d{1,2})\s*(?:日|号)?",
        search_text,
    )
    parsed = [_safe_date(int(year), int(month), int(day)) for year, month, day in explicit]
    parsed = [item for item in parsed if item]
    if parsed:
        return max(parsed)

    current_year_match = re.search(r"(20\d{2})\s*年", compact)
    current_year = int(current_year_match.group(1)) if current_year_match else date.today().year
    md_matches = re.findall(r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*(?:日|号)", search_text)
    parsed_md = [_safe_date(current_year, int(month), int(day)) for month, day in md_matches]
    parsed_md = [item for item in parsed_md if item]
    if parsed_md:
        future = [item for item in parsed_md if item >= date.today()]
        return max(future or parsed_md)

    return None


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None
