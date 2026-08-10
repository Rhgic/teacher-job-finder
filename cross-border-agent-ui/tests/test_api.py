from sqlalchemy import select

from app.models import AuditLog, Conversation, Draft, ReviewTask, Tenant


def _first_conversation(client, headers):
    response = client.get("/api/conversations", headers=headers)
    assert response.status_code == 200
    return response.json()[0]["id"]


def test_login_auth_and_static_exposure(client):
    assert client.get("/api/conversations").status_code == 401
    assert (
        client.post("/api/auth/login", json={"username": "agent", "password": "wrong"}).status_code
        == 401
    )
    assert client.get("/").status_code == 200
    assert client.get("/app.js").status_code == 200
    for hidden_file in ("/backend.py", "/test_backend.py", "/.env", "/app/main.py"):
        assert client.get(hidden_file).status_code == 404


def test_low_risk_draft_acceptance_writes_audit(client, agent_headers, db):
    conversation_id = _first_conversation(client, agent_headers)
    response = client.post(
        f"/api/conversations/{conversation_id}/messages",
        headers=agent_headers,
        json={"text": "Where is order #CB-20512?"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["human_review_required"] is False
    assert body["draft"]["citations"]
    trace = body["agent_trace"]
    assert [step["stage"] for step in trace] == [
        "language_intent",
        "risk_check",
        "order_query",
        "logistics_query",
        "knowledge_search",
        "draft_generation",
    ]
    assert trace[2]["status"] == "hit"
    assert trace[3]["status"] == "hit"
    assert trace[4] == {
        "stage": "knowledge_search",
        "status": "hit",
        "summary": "知识库关键词检索：命中 3 条引用",
        "meta": {"citations_count": 3},
    }
    # 轨迹只展示固定安全摘要，不能把原文、订单号或工具参数带回响应。
    trace_text = str(trace)
    assert "Where is order" not in trace_text
    assert "#CB-20512" not in trace_text
    accepted = client.post(
        f"/api/conversations/{conversation_id}/drafts/{body['draft']['id']}/accept",
        headers=agent_headers,
    )
    assert accepted.status_code == 200
    assert accepted.json()["draft"]["status"] == "accepted"
    assert db.scalar(select(AuditLog).where(AuditLog.action == "draft.accepted")) is not None
    # 新请求读取同一数据，证明不是浏览器内存状态。
    detail = client.get(f"/api/conversations/{conversation_id}", headers=agent_headers).json()
    assert any(
        d["id"] == body["draft"]["id"] and d["status"] == "accepted" for d in detail["drafts"]
    )


def test_high_risk_creates_review_agent_cannot_approve_admin_can_decide(
    client, agent_headers, admin_headers, db
):
    conversation_id = _first_conversation(client, agent_headers)
    created = client.post(
        f"/api/conversations/{conversation_id}/messages",
        headers=agent_headers,
        json={"text": "I want a refund for order #CB-20512"},
    )
    assert created.status_code == 200
    body = created.json()
    assert body["human_review_required"] is True
    assert body["review_task_id"]
    assert body["agent_trace"][-1] == {
        "stage": "human_review",
        "status": "blocked",
        "summary": "已创建人工审核单；系统未执行退款、外部消息或平台写操作",
        "meta": {"risk_level": "high"},
    }
    review_id = body["review_task_id"]
    assert (
        client.post(
            f"/api/reviews/{review_id}/approve", headers=agent_headers, json={"reason": "no"}
        ).status_code
        == 403
    )
    decision = client.post(
        f"/api/reviews/{review_id}/approve",
        headers=admin_headers,
        json={"reason": "订单与政策已由人工核对"},
    )
    assert decision.status_code == 200
    assert decision.json()["status"] == "approved"
    assert db.scalar(select(ReviewTask).where(ReviewTask.id == review_id)).reviewer_id is not None
    assert db.scalar(select(AuditLog).where(AuditLog.action == "review.approved")) is not None
    assert db.scalar(select(Draft).where(Draft.id == body["draft"]["id"])).status == "accepted"


def test_tenant_scoping_returns_not_found(client, admin_headers, db):
    tenant = Tenant(name="Isolated", slug="isolated")
    db.add(tenant)
    db.flush()
    hidden = Conversation(tenant_id=tenant.id, buyer_name="Other buyer", lang="en", status="open")
    db.add(hidden)
    db.commit()
    assert client.get(f"/api/conversations/{hidden.id}", headers=admin_headers).status_code == 404


def test_static_assets_are_not_cached(client):
    """静态资源必须带 Cache-Control: no-store。

    背景：修好 web/styles.css 的 [hidden] 规则后，服务端已返回新内容，
    浏览器却仍在用缓存的旧副本，差点被据此判成"修复无效"。
    在 index.html 手写 ?v= 参数要求每次改样式都记得递增，忘一次就失效；
    这里改成响应层强制，让"刷新即最新"不依赖记忆。
    """
    for path in ("/", "/styles.css", "/app.js", "/favicon.svg"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.headers.get("cache-control") == "no-store", path


def test_static_assets_never_return_304(client):
    """带条件请求头时也不得回 304。

    只设 no-store 不够：StaticFiles 仍会按 ETag / Last-Modified 命中协商缓存，
    浏览器照样复用本地旧副本，no-store 就形同虚设。
    """
    first = client.get("/styles.css")
    etag = first.headers.get("etag")
    assert first.status_code == 200

    conditional = client.get("/styles.css", headers={"If-None-Match": etag} if etag else {})
    assert conditional.status_code == 200
    assert conditional.headers.get("cache-control") == "no-store"


def test_no_store_does_not_expose_source_files(client):
    """关缓存不能顺带放宽暴露面：只有 web/ 下的资源可达。"""
    for hidden in ("/app/main.py", "/.env", "/pyproject.toml", "/tests/test_api.py"):
        assert client.get(hidden).status_code == 404, hidden
