"""查询扩展与占位模式打分测试。

背景：占位检索是词法匹配，怕"同义不同词"——用户问"工资多少"，
公告写"薪酬待遇"，字面对不上就零召回（实测 12 个口语问题有 7 个中招）。
用 LLM 把问法翻译成公告用词来补这一层，从而不必为语义检索
单独引入 embedding 供应商。
"""
import json

import pytest

from services import ratelimit, rag_qa
from services.llm_credentials import LLMCredential

CRED = LLMCredential(api_key="sk-test-key", model="deepseek-chat")
STUB_CRED = LLMCredential(api_key="", model="deepseek-chat", is_stub=True)


@pytest.fixture
def real_llm_mode(monkeypatch):
    monkeypatch.setattr(rag_qa.settings, "LLM_STUB_MODE", False)


def _fake_expand(monkeypatch, reply):
    monkeypatch.setattr(rag_qa, "_call_deepseek", lambda *a, **k: reply)


def test_expands_colloquial_question(monkeypatch, real_llm_mode):
    _fake_expand(monkeypatch, "薪酬、待遇、年薪、月薪")
    assert rag_qa.expand_query("工资多少？", cred=CRED) == {"薪酬", "待遇", "年薪", "月薪"}


def test_drops_single_chars_and_long_junk(monkeypatch, real_llm_mode):
    """单字太宽泛会把无关片段全放进来；超长的多半是模型没听话输出了句子。"""
    _fake_expand(monkeypatch, "薪、酬、薪酬、这是一句模型没有听懂指令时输出的完整句子")
    assert rag_qa.expand_query("工资多少？", cred=CRED) == {"薪酬"}


def test_stub_mode_skips_expansion(monkeypatch):
    """LLM 占位模式下不该产生任何调用。"""
    monkeypatch.setattr(rag_qa.settings, "LLM_STUB_MODE", True)

    def boom(*a, **k):
        raise AssertionError("stub 模式不该调用 LLM")

    monkeypatch.setattr(rag_qa, "_call_deepseek", boom)
    assert rag_qa.expand_query("工资多少？", cred=CRED) == set()


def test_expansion_failure_degrades_to_empty(monkeypatch, real_llm_mode):
    """扩展是增强项，失败必须退回原有召回而不是让问答挂掉。"""
    def boom(*a, **k):
        raise RuntimeError("api down")

    monkeypatch.setattr(rag_qa, "_call_deepseek", boom)
    assert rag_qa.expand_query("工资多少？", cred=CRED) == set()


def test_expansion_is_cached(monkeypatch, real_llm_mode):
    """同一问题不重复付费。"""
    store: dict[str, str] = {}
    monkeypatch.setattr(ratelimit, "cache_get", lambda k: store.get(k))
    monkeypatch.setattr(ratelimit, "cache_set", lambda k, v: store.__setitem__(k, v))
    calls = {"n": 0}

    def counted(*a, **k):
        calls["n"] += 1
        return "薪酬、待遇"

    monkeypatch.setattr(rag_qa, "_call_deepseek", counted)
    first = rag_qa.expand_query("工资多少？", cred=CRED)
    second = rag_qa.expand_query("工资多少？", cred=CRED)
    assert first == second == {"薪酬", "待遇"}
    assert calls["n"] == 1


def _seed(db):
    from models import DocChunk

    db.add(DocChunk(source_type="job", source_id="j1", source_title="A 校",
                    content="福利待遇：优厚薪酬，年薪 12-30 万，另有绩效奖金。",
                    chunk_index=0, embedding=json.dumps([0.1] * 256)))
    db.add(DocChunk(source_type="job", source_id="j2", source_title="B 校",
                    content="学校开设书法、形体、民乐等校本课程，环境优美。",
                    chunk_index=0, embedding=json.dumps([0.1] * 256)))
    db.commit()


@pytest.fixture
def db(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from models import Base

    engine = create_engine(f"sqlite:///{tmp_path / 't.db'}", future=True,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, future=True)() as session:
        _seed(session)
        yield session


def test_expansion_rescues_vocabulary_mismatch(db, monkeypatch, real_llm_mode):
    """核心场景：问"工资多少"，公告只写"薪酬待遇"，不扩展则召回不到。"""
    monkeypatch.setattr(rag_qa, "_call_deepseek", lambda *a, **k: "薪酬、待遇、年薪")

    without = rag_qa.retrieve(db, "工资多少？", expand=False, cred=CRED)
    with_expand = rag_qa.retrieve(db, "工资多少？", expand=True, cred=CRED)

    assert without == []
    assert [c.source_title for c in with_expand] == ["A 校"]


def test_scores_by_lexical_hit_not_dot_product(db, monkeypatch, real_llm_mode):
    """占位模式必须按词法命中打分。

    此前按哈希点积算分并卡 MIN_SCORE=0.08，导致"词明明命中了、
    却因为点积只有 0.04 被整体丢弃"。
    """
    monkeypatch.setattr(rag_qa, "_call_deepseek", lambda *a, **k: "薪酬、待遇")
    monkeypatch.setattr(rag_qa, "MIN_SCORE", 99.0)   # 点积路径下会全灭

    got = rag_qa.retrieve(db, "工资多少？", cred=CRED)

    assert [c.source_title for c in got] == ["A 校"]
    assert got[0].score > 0
