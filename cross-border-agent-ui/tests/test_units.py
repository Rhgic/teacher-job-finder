"""纯函数单测：脱敏、语言、意图、风险、工具参数校验、安全兜底。

这一层不碰数据库，跑得快，是改动后的第一道回归网。
"""

import pytest

from app.config import Settings as Settings_cls
from app.services.agent import classify_intent, detect_lang
from app.services.llm import (
    GENERATOR_DETERMINISTIC,
    build_deterministic_draft,
    validate_tool_arguments,
)
from app.services.redaction import redact
from app.services.risk import HIGH, LOW, classify_risk
from app.services.tools import extract_order_no


# ── 脱敏 ──────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "text,expect_email,expect_phone",
    [
        ("联系我 buyer@example.com", True, False),
        ("call me at +86 13800138000", False, True),
        ("mail buyer@shop.co and ring (415) 555-2671", True, True),
        ("订单 #CB-20512 到哪了", False, False),
    ],
)
def test_redact_email_and_phone(text, expect_email, expect_phone):
    out, changed = redact(text)
    assert ("[EMAIL]" in out) is expect_email
    assert ("[PHONE]" in out) is expect_phone
    assert changed is (expect_email or expect_phone)


def test_redact_keeps_order_number_intact():
    """订单号必须原样保留——它不是 PII，而且后面要拿它查库。"""
    out, _ = redact("Where is #CB-20512?")
    assert "#CB-20512" in out


def test_redact_ignores_short_digit_runs():
    """位数不足的数字串（金额、日期）不该被当成电话。"""
    out, changed = redact("订单金额 42.80，日期 07-26")
    assert "[PHONE]" not in out
    assert changed is False


# ── 语言 ──────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "text,lang",
    [
        ("我的包裹到哪了", "zh"),
        ("Wo ist meine Bestellung?", "de"),
        ("Pesanan saya belum sampai", "id"),
        ("Where is my package", "en"),
        ("", "en"),
    ],
)
def test_detect_lang(text, lang):
    assert detect_lang(text) == lang


# ── 意图 ──────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "text,intent",
    [
        ("Where is my order", "logistics"),
        ("the item arrived broken", "quality"),
        ("I want a refund", "refund"),
        ("when is my settlement", "settlement"),
        ("do you have a promo code", "coupon"),
        ("hello there", "general"),
    ],
)
def test_classify_intent(text, intent):
    assert classify_intent(text) == intent


# ── 风险 ──────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "text,risk_type",
    [
        ("I want a refund now", "refund"),
        ("请给我赔偿", "compensation"),
        ("when is the payout", "settlement"),
        ("I was charged twice", "payment"),
        ("please change address to another city", "address_change"),
        ("Ich möchte eine Rückerstattung", "refund"),
        ("saya mau pengembalian dana", "refund"),
    ],
)
def test_high_risk_types_detected(text, risk_type):
    """五类高风险必须命中，且四语种都要覆盖——
    买家不会用中文提退款，只匹配中文等于没有防线。"""
    v = classify_risk(text)
    assert v.level == HIGH
    assert v.risk_type == risk_type
    assert v.human_review_required is True


def test_low_risk_question_passes():
    v = classify_risk("Where is my order #CB-20512?")
    assert v.level == LOW
    assert v.human_review_required is False


# ── 安全兜底：无知识命中不得编造政策 ────────────────────────────────
@pytest.mark.parametrize("lang", ["zh", "en", "de", "id"])
def test_no_knowledge_hit_never_states_policy(lang):
    """检索无命中时，草稿只能说转人工/请补充信息，绝不能出现具体政策数字。

    这是防幻觉的最后一道闸：编造一条店铺没有的规则，比不回答代价大得多。
    """
    d = build_deterministic_draft(
        lang=lang, intent="general", escalate=False, order=None,
        logistics=None, kb_body="", buyer_name="",
    )
    assert d.generator == GENERATOR_DETERMINISTIC
    for forbidden in ("7 天", "7-day", "30 days", "%", "refund of", "退款金额"):
        assert forbidden not in d.body


@pytest.mark.parametrize("lang", ["zh", "en", "de", "id"])
def test_high_risk_draft_promises_nothing(lang):
    """高风险草稿不得出现金额或确定性承诺，只说明将转人工。"""
    d = build_deterministic_draft(
        lang=lang, intent="refund", escalate=True, order={"found": True, "amount": "USD 42.80"},
        logistics=None, kb_body="7 天无理由退货", buyer_name="Buyer-A",
    )
    assert "42.80" not in d.body
    assert "7 天" not in d.body


# ── 订单号抽取 ────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "text,expected",
    [
        ("Where is #CB-20512", "#CB-20512"),
        ("order cb-20485 please", "#CB-20485"),
        ("my shipping was refund delayed", None),  # 普通单词不得被当成订单号
        ("", None),
    ],
)
def test_extract_order_no(text, expected):
    assert extract_order_no(text) == expected


# ── 工具参数白名单 ────────────────────────────────────────────────
def test_tool_arguments_accept_valid():
    assert validate_tool_arguments("query_order", {"order_no": "#CB-20512"}) == {
        "order_no": "#CB-20512"
    }


@pytest.mark.parametrize(
    "name,args",
    [
        ("drop_table", {"x": 1}),                       # 白名单外的工具
        ("query_order", {"order_no": "#CB-1", "tenant_id": 2}),  # 越权字段
        ("query_order", {}),                            # 缺必填
        ("query_order", "not-a-dict"),                  # 类型非法
        ("search_kb", {"query": "x", "lang": "fr"}),    # 语种不在枚举内
    ],
)
def test_tool_arguments_reject_invalid(name, args):
    """非法工具调用必须返回 None 让调用方安全回退，而不是抛异常或放行。"""
    assert validate_tool_arguments(name, args) is None


# ── JWT 密钥强度（P0）────────────────────────────────────────────────
def test_short_jwt_secret_is_rejected(monkeypatch):
    """弱密钥必须让服务启动失败，而不是只发一条容易被忽略的警告。

    PyJWT 对短密钥只发 InsecureKeyLengthWarning；靠警告防不住把
    dev-only-change-me 原样带上线——那等于把签发 admin token 的能力公开。
    """
    from pydantic import ValidationError

    from app.config import Settings

    monkeypatch.setenv("JWT_SECRET", "too-short")
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings(_env_file=None)


def test_long_jwt_secret_accepted(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "a" * 64)
    assert len(Settings_cls(_env_file=None).jwt_secret) == 64


# ── 二次风险检查回归（P0）──────────────────────────────────────────
_QUALITY_KB = "Damaged items are eligible for a full refund or replacement within 30 days."


def test_quoted_policy_is_not_a_commitment():
    """引用的政策正文里出现 refund，不等于我方做出了退款承诺。

    这是「the item arrived broken」被误升 high 的根因：
    二次检查原本直接把入站关键词套在草稿上，而草稿必然包含引用的政策原文。
    """
    from app.services.risk import contains_commitment

    draft = f"Hi Buyer-A! {_QUALITY_KB}"
    assert contains_commitment(draft, quoted_policy=_QUALITY_KB) is False


@pytest.mark.parametrize(
    "draft",
    [
        "We will refund you within 3 business days.",
        "我们将为你退款",
        "已为你退款",
        "Kami akan refund pesanan Anda",
        "We have updated your address.",
    ],
)
def test_real_commitments_still_escalate(draft):
    """收窄不能放过真承诺：我方明确表示将执行资金或收货变更时仍须转人工。"""
    from app.services.risk import contains_commitment

    assert contains_commitment(draft, quoted_policy=_QUALITY_KB) is True


def test_inbound_risk_unchanged_by_second_pass_narrowing():
    """入站判定不受影响——真正的退款/赔付/支付/改地址诉求仍在第一道就被拦下。"""
    from app.services.risk import HIGH, classify_risk

    for text, rtype in [
        ("I want a refund", "refund"),
        ("请赔偿我", "compensation"),
        ("when is my payout", "settlement"),
        ("I was charged twice", "payment"),
        ("please change address", "address_change"),
    ]:
        v = classify_risk(text)
        assert v.level == HIGH and v.risk_type == rtype
