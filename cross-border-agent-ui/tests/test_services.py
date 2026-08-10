import asyncio
from types import SimpleNamespace

from app.models import KnowledgeArticle, Tenant
from app.services import agent, llm, retrieval, tools
from app.services.redaction import contains_pii, redact
from app.services.risk import HIGH, classify_risk


def test_language_intent_and_pii_redaction():
    assert agent.detect_lang("我的包裹到哪里了？") == "zh"
    assert agent.detect_lang("Wo ist meine Lieferung?") == "de"
    assert agent.detect_lang("Kapan pesanan saya sampai?") == "id"
    assert agent.classify_intent("Where is my shipment?") == "logistics"
    value, changed = redact("mail me@example.com or call +86 13800138000")
    assert changed and "me@example.com" not in value and "13800138000" not in value
    assert "[EMAIL]" in value and "[PHONE]" in value and not contains_pii(value)


def test_all_sensitive_requests_require_human_review():
    for text in (
        "please refund",
        "I need compensation",
        "when is seller payout",
        "my payment charged twice",
        "change address",
    ):
        verdict = classify_risk(text)
        assert verdict.level == HIGH
        assert verdict.human_review_required


def test_no_knowledge_hit_never_promises_policy(db):
    tenant_id = db.query(Tenant.id).filter(Tenant.slug == "demo-shop").scalar()
    hit = retrieval.search(db, tenant_id, "unrelated nebula question", lang="en", intent="general")
    assert hit == []
    draft = llm.build_deterministic_draft(
        lang="en", intent="general", escalate=False, order=None, logistics=None, kb_body=""
    )
    assert "human colleague" in draft.body
    assert "refund" not in draft.body.lower()


def test_retrieval_and_order_are_tenant_isolated(db):
    primary_id = db.query(Tenant.id).filter(Tenant.slug == "demo-shop").scalar()
    other = Tenant(name="Other demo tenant", slug="other-demo")
    db.add(other)
    db.flush()
    db.add(
        KnowledgeArticle(
            tenant_id=other.id,
            title="Secret",
            body="not visible",
            lang="en",
            keywords=["secret"],
            is_active=True,
        )
    )
    db.commit()
    assert retrieval.search(db, primary_id, "secret", lang="en") == []
    assert tools.query_order(db, other.id, "#CB-20512").found is False


def test_llm_failure_and_illegal_tool_arguments_fallback(monkeypatch):
    settings = SimpleNamespace(
        llm_enabled=True,
        llm_timeout_seconds=0.1,
        deepseek_base="http://bad",
        deepseek_api_key="x",
        deepseek_model="x",
    )
    monkeypatch.setattr(llm, "get_settings", lambda: settings)

    class BrokenClient:
        async def __aenter__(self):
            raise RuntimeError("network unavailable")

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **_: BrokenClient())
    result = asyncio.run(
        llm.try_deepseek_draft(
            redacted_message="where is my order", lang="en", kb_body="policy", order=None
        )
    )
    assert result is None
    assert llm.validate_tool_arguments("drop_database", {}) is None
    assert llm.validate_tool_arguments("query_order", {"order_no": "#CB-1", "tenant_id": 9}) is None
    assert llm.validate_tool_arguments("query_order", {"order_no": "#CB-1"}) == {
        "order_no": "#CB-1"
    }
