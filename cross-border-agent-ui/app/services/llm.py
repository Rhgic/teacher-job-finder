"""草稿生成：本地确定性生成器（默认）+ 可选 DeepSeek 适配器。

默认路径不需要任何外部 Key，Demo 随时可跑。DeepSeek 只是可选增强，
且**任何异常都回退确定性草稿**——演示链路不能因为第三方抖动而中断。

安全约束（对应规格 3.3）：
- 送进模型的文本必须已脱敏，函数入口再断言一次，防止调用方漏做
- 工具白名单固定，模型不能要求调用白名单外的东西
- 第三方错误原文不返回给用户，只记录错误类别
"""

import logging
from dataclasses import dataclass
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from app.config import get_settings
from app.services.redaction import contains_pii

log = logging.getLogger(__name__)

# 模型可调用的工具白名单。写死在这里，不接受模型自由发挥。
ALLOWED_TOOLS = ("query_order", "query_logistics", "search_kb")


# extra="forbid" 必须配在 model_config 上：Pydantic v2 的 model_validate()
# 不接受 extra 关键字参数，写在调用处会抛 TypeError（而且 except ValidationError
# 捕不到，异常会直接冒到调用方）。
class _OrderToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_no: str


class _SearchKbToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    lang: Literal["zh", "en", "de", "id"] = "en"


_TOOL_ARGUMENT_MODELS = {
    "query_order": _OrderToolArgs,
    "query_logistics": _OrderToolArgs,
    "search_kb": _SearchKbToolArgs,
}


def validate_tool_arguments(name: str, arguments: object) -> dict | None:
    """校验可选 LLM 适配器的工具调用参数。

    当前 V1 的 DeepSeek 请求不开放 function calling；这个白名单边界仍保留在
    适配器层，避免未来接入时把模型输出直接传给数据库工具。非法名称、未知字段、
    缺失字段都会返回 ``None``，由调用方安全回退而不是执行任何工具。
    """
    model = _TOOL_ARGUMENT_MODELS.get(name)
    if model is None or not isinstance(arguments, dict):
        return None
    try:
        # 模型上已配 extra="forbid"：防止塞入 tenant_id、SQL 或未声明的控制字段。
        return model.model_validate(arguments).model_dump()
    except ValidationError:
        return None


GENERATOR_DETERMINISTIC = "deterministic"
GENERATOR_DEEPSEEK = "deepseek"
GENERATOR_FALLBACK = "deepseek_fallback"

# 没有检索到任何政策依据时的安全兜底：只承诺转人工，绝不复述政策。
# 这条是防幻觉的最后一道闸——宁可少答，不能编造店铺没有的规则。
_NO_BASIS = {
    "zh": "你好，这个问题我需要与人工同事确认后再答复，以免给你不准确的信息。"
    "方便补充一下订单号或具体情况吗？",
    "en": "Hi! I'd rather check this with a human colleague before answering, so I don't give you "
    "anything inaccurate. Could you share your order number or a bit more detail?",
    "de": "Hallo! Ich kläre das lieber mit einer Kollegin ab, bevor ich dir etwas Falsches sage. "
    "Kannst du mir deine Bestellnummer oder mehr Details nennen?",
    "id": "Halo! Saya cek dulu dengan rekan tim agar tidak memberi info yang keliru. "
    "Boleh kirim nomor pesanan atau detail tambahan?",
}

# 命中高风险时的统一措辞：明确说明会转人工，且不承诺任何金额或时限。
_ESCALATE = {
    "zh": "你好，关于这笔诉求我已记录，将转交人工专员按政策复核后回复你。请稍候。",
    "en": "Hi! I've logged your request and passed it to a human specialist for review "
    "against our policy. We'll get back to you.",
    "de": "Hallo! Ich habe deine Anfrage aufgenommen und an eine Spezialistin zur Prüfung "
    "weitergeleitet. Wir melden uns.",
    "id": "Halo! Permintaan Anda sudah saya catat dan diteruskan ke spesialis untuk ditinjau "
    "sesuai kebijakan. Mohon ditunggu.",
}

_STATUS_I18N = {
    "在途": {"en": "in transit", "de": "unterwegs", "id": "dalam perjalanan"},
    "运输中": {"en": "in transit", "de": "unterwegs", "id": "dalam perjalanan"},
    "清关延误": {"en": "held at customs", "de": "im Zoll", "id": "tertahan di bea cukai"},
    "已退回": {"en": "returned to warehouse", "de": "retourniert", "id": "dikembalikan"},
    "已签收": {"en": "delivered", "de": "zugestellt", "id": "diterima"},
    "已完成": {"en": "completed", "de": "abgeschlossen", "id": "selesai"},
}


def _tr_status(status: str | None, lang: str) -> str:
    if not status or lang == "zh":
        return status or ""
    return _STATUS_I18N.get(status, {}).get(lang, status)


@dataclass(frozen=True)
class DraftResult:
    body: str
    generator: str


def _greeting(lang: str, name: str) -> str:
    who = f" {name}" if name else ""
    return {
        "zh": f"{name}你好，" if name else "你好，",
        "en": f"Hi{who}! ",
        "de": f"Hallo{who}! ",
        "id": f"Halo{who}! ",
    }.get(lang, f"Hi{who}! ")


def build_deterministic_draft(
    *,
    lang: str,
    intent: str,
    escalate: bool,
    order: dict | None,
    logistics: dict | None,
    kb_body: str,
    buyer_name: str = "",
) -> DraftResult:
    """本地确定性草稿。同样的输入永远得到同样的输出，可直接单测。"""
    lang = lang if lang in ("zh", "en", "de", "id") else "en"

    # 高风险：只说转人工，不复述金额、不承诺时限
    if escalate:
        return DraftResult(body=_ESCALATE[lang], generator=GENERATOR_DETERMINISTIC)

    # 无政策依据：安全兜底，绝不编造
    if not kb_body:
        return DraftResult(body=_NO_BASIS[lang], generator=GENERATOR_DETERMINISTIC)

    head = _greeting(lang, buyer_name)

    if intent == "logistics" and order and order.get("found"):
        status = _tr_status(order.get("status"), lang)
        ship = order.get("shipping_summary") or ""
        steps = (logistics or {}).get("steps") or []
        latest = steps[-1] if steps else ship
        tmpl = {
            "zh": f"{head}已为你查询订单 {order.get('order_no')}：{status}（{latest}）。{kb_body}",
            "en": f"{head}I checked order {order.get('order_no')}: {status} ({latest}). {kb_body}",
            "de": f"{head}Ich habe Bestellung {order.get('order_no')} geprüft: {status} "
            f"({latest}). {kb_body}",
            "id": f"{head}Saya cek pesanan {order.get('order_no')}: {status} ({latest}). {kb_body}",
        }
        return DraftResult(body=tmpl[lang], generator=GENERATOR_DETERMINISTIC)

    return DraftResult(body=f"{head}{kb_body}", generator=GENERATOR_DETERMINISTIC)


async def try_deepseek_draft(
    *,
    redacted_message: str,
    lang: str,
    kb_body: str,
    order: dict | None,
) -> DraftResult | None:
    """可选增强路径。返回 None 表示未启用或失败——调用方据此回退确定性草稿。

    刻意不在这里抛异常：草稿生成失败不该让整条会话 500。
    """
    settings = get_settings()
    if not settings.llm_enabled:
        return None

    # 入口断言：绝不把未脱敏文本送出去。调用方漏做时在这里拦下。
    if contains_pii(redacted_message):
        log.warning("llm_input_contains_pii", extra={"stage": "llm", "action": "skip"})
        return None

    system = (
        "You are a cross-border e-commerce support assistant. "
        "Answer ONLY using the provided policy excerpt and order facts. "
        "If they do not cover the question, say you will escalate to a human. "
        "Never promise refunds, compensation, or specific amounts. "
        "Reply in the same language as the buyer."
    )
    user = (
        f"Buyer language: {lang}\n"
        f"Policy excerpt: {kb_body or '(none)'}\n"
        f"Order facts: {order or '(none)'}\n"
        f"Buyer message: {redacted_message}"
    )

    try:
        timeout = httpx.Timeout(settings.llm_timeout_seconds, connect=5.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{settings.deepseek_base}/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
                json={
                    "model": settings.deepseek_model,
                    "temperature": 0.2,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                },
            )
            resp.raise_for_status()
            body = (resp.json()["choices"][0]["message"]["content"] or "").strip()
    except Exception as exc:  # noqa: BLE001 — 第三方任何异常都回退，不影响会话
        # 只记错误类别，不记第三方返回体（可能含请求回显）
        log.warning("llm_call_failed", extra={"stage": "llm", "error_class": type(exc).__name__})
        return None

    if not body:
        return None
    return DraftResult(body=body, generator=GENERATOR_DEEPSEEK)
