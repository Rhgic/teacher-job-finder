"""风险分类与安全路由。

产品红线：AI 只产出草稿。凡涉及资金流向或收货信息变更的诉求，一律建人工审核单，
系统不执行任何资金或平台写操作，前端也不提供"自动发送"。

判定刻意做成纯函数、纯规则、无模型参与：
风控是要担责的地方，必须可枚举、可单测、可在代码评审里逐条对着看。
模型判错没人能解释，规则判错至少能指到是哪一行。
"""

import re
from dataclasses import dataclass

# 五类高风险，与规格一致。关键词覆盖中/英/德/印尼四语种——
# 买家不会用中文提退款，只匹配中文等于没有防线。
RISK_RULES: list[tuple[str, tuple[str, ...]]] = [
    (
        "refund",
        (
            "退款",
            "退钱",
            "退货退款",
            "refund",
            "money back",
            "reimburse",
            "rückerstattung",
            "erstattung",
            "geld zurück",
            "pengembalian dana",
            "refund",
            "uang kembali",
            "kembalikan uang",
        ),
    ),
    (
        "compensation",
        (
            "赔付",
            "赔偿",
            "补偿",
            "索赔",
            "compensation",
            "compensate",
            "claim damages",
            "entschädigung",
            "schadenersatz",
            "kompensasi",
            "ganti rugi",
        ),
    ),
    (
        "settlement",
        (
            "结算",
            "回款",
            "放款",
            "提现",
            "佣金",
            "settlement",
            "settle",
            "payout",
            "withdraw funds",
            "commission",
            "abrechnung",
            "auszahlung",
            "pencairan",
            "penarikan dana",
            "komisi",
        ),
    ),
    (
        "payment",
        (
            "支付",
            "付款",
            "扣款",
            "重复扣费",
            "信用卡",
            "payment",
            "charge",
            "charged twice",
            "double charge",
            "credit card",
            "zahlung",
            "abbuchung",
            "kreditkarte",
            "pembayaran",
            "kartu kredit",
            "tagihan",
        ),
    ),
    (
        "address_change",
        (
            "改地址",
            "修改地址",
            "换地址",
            "更改收货",
            "change address",
            "change the address",
            "update address",
            "new shipping address",
            "wrong address",
            "adresse ändern",
            "lieferadresse ändern",
            "ubah alamat",
            "ganti alamat",
            "alamat salah",
        ),
    ),
]

LOW = "low"
HIGH = "high"


@dataclass(frozen=True)
class RiskVerdict:
    level: str
    risk_type: str | None
    matched: tuple[str, ...]

    @property
    def human_review_required(self) -> bool:
        return self.level == HIGH


def classify_risk(text: str) -> RiskVerdict:
    """按关键词判定风险。命中任意一类即 high。

    命中多类时取第一类作为 risk_type（顺序即优先级：资金 > 收货信息），
    但 matched 会带上全部命中词，审核人能看到完整依据。
    """
    t = (text or "").lower()
    hits: list[str] = []
    first_type: str | None = None

    for risk_type, keywords in RISK_RULES:
        for kw in keywords:
            if kw.lower() in t:
                hits.append(kw)
                if first_type is None:
                    first_type = risk_type
                break  # 同一类记一次即可

    if first_type:
        return RiskVerdict(level=HIGH, risk_type=first_type, matched=tuple(hits))
    return RiskVerdict(level=LOW, risk_type=None, matched=())


def risk_type_label(risk_type: str | None) -> str:
    return {
        "refund": "退款",
        "compensation": "赔付",
        "settlement": "结算",
        "payment": "支付",
        "address_change": "地址修改",
    }.get(risk_type or "", "未分类")


# ── 出站前的二次检查 ────────────────────────────────────────────────
# 与入站检查是两件事，不能共用一套关键词。
#
# 入站扫的是买家诉求："我要退款" → 必须转人工。
# 出站扫的是我方草稿：草稿里出现 "refund" 三个字母**本身不构成风险**——
# 引用的退货政策正文里必然含这个词。原实现直接把 classify_risk 套在草稿上，
# 于是"东西到了但坏了"这种质量问题，只因引用的政策提到 refund 就被升为 high。
#
# 真正该拦的是**我方做出的承诺**：主语是我们、动词是将要执行资金或收货变更动作。
# 所以这里只匹配"第一人称 + 承诺动词"，且先把引用的政策原文剔除再扫。
_COMMITMENT_RE = re.compile(
    # en：we/I will refund、we have refunded、we'll issue a refund、we will compensate…
    r"\b(?:we|i)\s*(?:'ll|will|have|has|are going to|shall)\s+\w*\s*"
    r"(?:refund|reimburse|compensate|repay|credit|issue a refund|pay you)\b"
    r"|\b(?:refunded|reimbursed|compensated)\s+(?:you|your)\b"
    r"|\bhas been (?:refunded|processed|credited)\b"
    r"|\bwe (?:have )?(?:changed|updated) (?:your|the) address\b"
    # zh：我们将/已为你 退款、赔付、改地址
    r"|(?:我们|本店)(?:[将会]|已经?|马上|尽快|为[你您])*\s*(?:退款|退回货款|赔付|赔偿|补偿|打款)(?!政策|规则|条款|流程|说明|标准)"
    r"|已(?:经)?(?:为[你您])?(?:成功)?(?:退款|退回货款|赔付|打款)"
    r"|(?:已|将)(?:为你|为您)?(?:修改|变更|更改)(?:收货)?地址"
    # de
    r"|\bwir\s+(?:werden|haben)\s+\w*\s*(?:erstatt\w+|entschädig\w+|zurückgezahlt)"
    # id
    r"|\bkami\s+(?:akan|sudah|telah)\s+\w*\s*(?:refund|mengembalikan|mengganti|membayar)",
    re.IGNORECASE,
)


def contains_commitment(draft_body: str, quoted_policy: str = "") -> bool:
    """草稿是否做出了资金或收货信息变更的**承诺**。

    quoted_policy 是本次引用的知识库正文；先从草稿里剔除，
    避免"引用了政策"被误判成"做出了承诺"。
    """
    text = draft_body or ""
    if quoted_policy:
        text = text.replace(quoted_policy, " ")
    return bool(_COMMITMENT_RE.search(text))
