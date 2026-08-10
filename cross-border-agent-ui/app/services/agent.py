"""客服处理管道。

    脱敏 → 语言/意图 → 风险 → 订单/物流工具 → 知识库检索
      → 草稿 → 二次风险检查 → 低风险待采纳 / 高风险建审核单 → 写库与审计

为什么不用 LangGraph：这条链路是固定顺序、无循环、无回溯的直线，
用普通函数就能表达，还能直接单测每一段。引入编排框架只会增加一层
运行时抽象和调试成本，换不来任何东西（详见 ARCHITECTURE.md）。

本模块只做编排与落库，具体判定都委托给 risk / retrieval / tools / llm，
这样每一块都能单独测。
"""

import logging
import re
import time
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import Conversation, Draft, Message, ReviewTask
from app.services import audit, llm, retrieval, tools
from app.services.redaction import redact
from app.services.risk import HIGH, classify_risk, contains_commitment

log = logging.getLogger("app.agent")

# ── 语言识别 ────────────────────────────────────────────────────────
# 中文/德语先看特征字符，再用高频功能词打分。
# 不做概率模型——四语种、短文本，词表足够且可解释。

_DE_WORDS = frozenset(
    """ich der die das und für wie ist eine mit nicht sie er es auf von zu haben werde
    lieferung dauert zoll rückerstattung bestellung geld zurück wann wo""".split()
)
_ID_WORDS = frozenset(
    """saya ini apa mengapa bisa apakah sudah belum untuk dengan dan di ke yang tidak mau
    retur pengiriman estimasi bea cacat rusak kembali pesanan barang lama kapan""".split()
)


def detect_lang(text: str) -> str:
    t = text or ""
    if not t.strip():
        return "en"
    if re.search(r"[一-鿿]", t):
        return "zh"
    if re.search(r"[äöüßÄÖÜ]", t):
        return "de"
    toks = set(re.findall(r"[a-zà-ÿ]+", t.lower()))
    de_hits = len(toks & _DE_WORDS)
    id_hits = len(toks & _ID_WORDS)
    if de_hits and de_hits >= id_hits:
        return "de"
    if id_hits:
        return "id"
    return "en"


# ── 意图识别 ────────────────────────────────────────────────────────
# 注意：意图 ≠ 风险。意图决定查什么、检索什么；风险决定能不能自动出站。
# 两者分开是刻意的——"询问退款政策"和"要求退款"意图相同、风险不同。

# 顺序即优先级，**更具体的意图必须排在更宽泛的前面**。
# 踩过的坑：logistics 原本排第一，其关键词 "arrive" 会子串命中 "arrived"，
# 于是「the item arrived broken」这类质量投诉被判成查物流，接着去查轨迹、
# 检索清关政策，答非所问。logistics 词表最宽，放最后兜底。
_INTENT_RULES: list[tuple[str, tuple[str, ...]]] = [
    (
        "quality",
        (
            "质量",
            "瑕疵",
            "破损",
            "坏了",
            "货不对板",
            "描述不符",
            "quality",
            "defective",
            "broken",
            "damaged",
            "not as described",
            "faulty",
            "qualität",
            "beschädigt",
            "defekt",
            "cacat",
            "rusak",
            "tidak sesuai",
        ),
    ),
    (
        "refund",
        ("退款", "退货", "refund", "return", "rückerstattung", "pengembalian", "retur"),
    ),
    (
        "settlement",
        ("结算", "回款", "佣金", "settlement", "payout", "commission", "abrechnung", "pencairan"),
    ),
    (
        "coupon",
        ("优惠券", "折扣", "coupon", "promo", "voucher", "gutschein", "diskon", "kode promo"),
    ),
    (
        "logistics",
        (
            "物流",
            "清关",
            "包裹",
            "快递",
            "几天",
            "多久",
            "到哪",
            "logistics",
            "shipping",
            "track",
            "where is",
            "customs",
            "delay",
            "delivery",
            "eta",
            "arrive",
            "lieferung",
            "lieferzeit",
            "dauert",
            "zoll",
            "wo ist",
            "pengiriman",
            "estimasi",
            "bea cukai",
            "sampai",
            "lama",
            "resi",
        ),
    ),
]


def classify_intent(text: str) -> str:
    t = (text or "").lower()
    for intent, keywords in _INTENT_RULES:
        if any(k in t for k in keywords):
            return intent
    return "general"


# ── 管道 ───────────────────────────────────────────────────────────


@dataclass
class PipelineOutcome:
    run_id: str
    message: Message
    draft: Draft
    review_task: ReviewTask | None
    lang: str
    intent: str
    risk_level: str
    risk_type: str | None
    citations: list[int]
    generator: str

    @property
    def human_review_required(self) -> bool:
        return self.review_task is not None


async def process_buyer_message(
    db: Session,
    *,
    tenant_id: int,
    conversation: Conversation,
    raw_text: str,
    actor_id: int | None = None,
) -> PipelineOutcome:
    """处理一条买家消息，返回落库后的结果。调用方负责 commit。"""
    run_id = uuid.uuid4().hex[:12]
    started = time.perf_counter()

    # ① 脱敏 —— 入库和送模型的都是脱敏后的文本，原文不落库
    redacted_text, was_redacted = redact(raw_text)

    # ② 语言与意图
    lang = detect_lang(redacted_text) or conversation.lang or "en"
    intent = classify_intent(redacted_text)

    # ③ 风险（第一次）：决定这条诉求能不能走自动路径
    verdict = classify_risk(redacted_text)

    # ④ 工具：只查演示库，且带 tenant_id
    order_no = tools.extract_order_no(redacted_text)
    order_info = (
        tools.query_order(db, tenant_id, order_no).to_dict() if order_no else {"found": False}
    )
    logistics_info = (
        tools.query_logistics(db, tenant_id, order_no).to_dict()
        if order_no and intent == "logistics"
        else {"found": False}
    )

    # ⑤ 检索
    hits = retrieval.search(db, tenant_id, redacted_text, lang=lang, intent=intent)
    kb_body = retrieval.pick_body(hits, lang)
    citations = [h.article_id for h in hits]

    # ⑥ 草稿：默认确定性；启用 DeepSeek 时尝试增强，失败静默回退
    draft_result = llm.build_deterministic_draft(
        lang=lang,
        intent=intent,
        escalate=verdict.level == HIGH,
        order=order_info,
        logistics=logistics_info,
        kb_body=kb_body,
        buyer_name=conversation.buyer_name,
    )
    if verdict.level != HIGH:
        # 高风险不走模型：那条路径的措辞必须完全可控，不能让模型自由发挥。
        enhanced = await llm.try_deepseek_draft(
            redacted_message=redacted_text, lang=lang, kb_body=kb_body, order=order_info
        )
        if enhanced is not None:
            draft_result = enhanced
        elif llm.get_settings().llm_enabled:
            # 启用了却没拿到结果 = 回退过，标记出来，别让人以为是模型写的
            draft_result = llm.DraftResult(body=draft_result.body, generator=llm.GENERATOR_FALLBACK)

    # ⑦ 风险（第二次）：出站前看草稿**有没有做出承诺**。
    #
    # 这里刻意不复用入站的 classify_risk：那套关键词扫的是买家诉求，
    # 套到草稿上会把"引用了退货政策"当成"承诺了退款"——实测「the item arrived
    # broken」这类质量问题，只因引用的政策正文含 refund 就被升为 high。
    # 二次检查只该拦"我方将要执行资金/收货变更"的措辞，所以先剔除引用的政策原文，
    # 再匹配第一人称承诺句式。
    #
    # 入站那道判定不受影响：真正的退款/赔付/支付/改地址诉求在第 ③ 步就已经拦下，
    # 这里只是模型自由发挥时的兜底。
    draft_committed = contains_commitment(draft_result.body, quoted_policy=kb_body)
    final_high = verdict.level == HIGH or draft_committed
    final_risk_type = verdict.risk_type or (
        classify_risk(draft_result.body).risk_type if draft_committed else None
    )

    if final_high and draft_result.generator != llm.GENERATOR_DETERMINISTIC:
        # 二次检查才发现风险 → 丢弃模型草稿，换回可控的转人工措辞
        draft_result = llm.build_deterministic_draft(
            lang=lang,
            intent=intent,
            escalate=True,
            order=order_info,
            logistics=logistics_info,
            kb_body=kb_body,
            buyer_name=conversation.buyer_name,
        )

    # ⑧ 落库
    message = Message(
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        sender="buyer",
        body=redacted_text,
        was_redacted=was_redacted,
    )
    db.add(message)
    db.flush()

    draft = Draft(
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        message_id=message.id,
        body=draft_result.body,
        lang=lang,
        intent=intent,
        citations=citations,
        risk_level=HIGH if final_high else "low",
        status="blocked" if final_high else "pending_agent",
        generator=draft_result.generator,
    )
    db.add(draft)
    db.flush()

    review_task: ReviewTask | None = None
    if final_high:
        review_task = ReviewTask(
            tenant_id=tenant_id,
            draft_id=draft.id,
            conversation_id=conversation.id,
            risk_type=final_risk_type or "refund",
            status="pending",
        )
        db.add(review_task)
        db.flush()

    audit.record(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="message.processed",
        object_type="message",
        object_id=message.id,
        meta={
            "run_id": run_id,
            "lang": lang,
            "intent": intent,
            "risk_level": draft.risk_level,
            "risk_type": final_risk_type,
            "draft_id": draft.id,
            "generator": draft.generator,
            "citations_count": len(citations),
        },
    )

    # 不记正文、订单号、邮箱或电话；run_id 用于把一次处理的结构化日志与审计关联。
    log.info(
        "agent_processed",
        extra={
            "run_id": run_id,
            "stage": "completed",
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "risk_level": draft.risk_level,
            "risk_type": final_risk_type,
            "generator": draft.generator,
            "citations_count": len(citations),
        },
    )

    return PipelineOutcome(
        run_id=run_id,
        message=message,
        draft=draft,
        review_task=review_task,
        lang=lang,
        intent=intent,
        risk_level=draft.risk_level,
        risk_type=final_risk_type,
        citations=citations,
        generator=draft.generator,
    )
