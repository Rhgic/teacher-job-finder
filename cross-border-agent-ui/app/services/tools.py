"""模拟订单与物流工具适配器。

只读演示数据库，**不连接任何真实店铺、物流或支付平台**。
函数签名保持与真实适配器一致（订单号进、结构化结果出），
将来换成真实 API 时替换实现即可，调用方不用改。

所有查询都带 tenant_id：订单是跨租户泄露风险最高的对象。
"""

import re
from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Order

ORDER_NO_RE = re.compile(r"#?\s*(CB-\d{3,10})", re.IGNORECASE)


@dataclass(frozen=True)
class OrderInfo:
    found: bool
    order_no: str | None = None
    platform: str | None = None
    country: str | None = None
    amount: str | None = None
    status: str | None = None
    shipping_summary: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class LogisticsInfo:
    found: bool
    order_no: str | None = None
    steps: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        d = asdict(self)
        d["steps"] = list(self.steps)
        return d


def extract_order_no(text: str) -> str | None:
    """从买家消息里抽订单号。

    只认 CB-数字 这一种形态。刻意不做"任意字母数字串"的宽松匹配——
    那样会把 shipping、refund 这类普通单词当成订单号，拿去查库必然查不到。
    """
    m = ORDER_NO_RE.search(text or "")
    if not m:
        return None
    return "#" + m.group(1).upper()


def _fetch(db: Session, tenant_id: int, order_no: str) -> Order | None:
    if not order_no:
        return None
    return db.scalar(select(Order).where(Order.tenant_id == tenant_id, Order.order_no == order_no))


def query_order(db: Session, tenant_id: int, order_no: str) -> OrderInfo:
    o = _fetch(db, tenant_id, order_no)
    if o is None:
        return OrderInfo(found=False, order_no=order_no)
    return OrderInfo(
        found=True,
        order_no=o.order_no,
        platform=o.platform,
        country=o.country,
        amount=f"{o.currency} {o.amount:.2f}",
        status=o.status,
        shipping_summary=o.shipping_summary,
    )


def query_logistics(db: Session, tenant_id: int, order_no: str) -> LogisticsInfo:
    o = _fetch(db, tenant_id, order_no)
    if o is None or not o.logistics_steps:
        return LogisticsInfo(found=False, order_no=order_no)
    return LogisticsInfo(found=True, order_no=o.order_no, steps=tuple(o.logistics_steps))
