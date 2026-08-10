"""最小化 PII 脱敏：邮箱与电话号码。

范围是刻意收窄的。V1 只声明覆盖邮箱和电话这两类高频、正则可靠的字段——
人名、街道地址在多语种下正则召回极低，与其做个半吊子的然后对外宣称"已脱敏"，
不如明确写清没覆盖什么（README 的"未实现"一节里也如实列出）。

脱敏发生在消息入库之前，也发生在送进模型之前：库里和模型侧都只有占位符。
"""

import re

EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")

# 电话：覆盖 +86 13800138000 / (415) 555-2671 / 415-555-2671 / 13800138000 这几类常见写法。
# 要求至少 7 位数字，避免把订单号、金额、日期误当电话。
PHONE_RE = re.compile(
    r"(?<![\w-])(?:\+\d{1,3}[\s-]?)?(?:\(\d{2,4}\)[\s-]?)?\d(?:[\d\s-]{5,}\d)(?![\w-])"
)

EMAIL_PLACEHOLDER = "[EMAIL]"
PHONE_PLACEHOLDER = "[PHONE]"


def _digit_count(s: str) -> int:
    return sum(c.isdigit() for c in s)


def redact(text: str) -> tuple[str, bool]:
    """返回 (脱敏后的文本, 是否发生过脱敏)。

    先替换邮箱再替换电话：邮箱里可能含数字串，先处理掉可避免电话正则啃进邮箱。
    """
    if not text:
        return "", False

    redacted = EMAIL_RE.sub(EMAIL_PLACEHOLDER, text)
    changed = redacted != text

    def _phone_sub(m: re.Match) -> str:
        # 位数不足视为普通数字（订单号、金额、日期），不动它
        if _digit_count(m.group(0)) < 7:
            return m.group(0)
        return PHONE_PLACEHOLDER

    after_phone = PHONE_RE.sub(_phone_sub, redacted)
    changed = changed or after_phone != redacted
    return after_phone, changed


def contains_pii(text: str) -> bool:
    _, changed = redact(text or "")
    return changed
