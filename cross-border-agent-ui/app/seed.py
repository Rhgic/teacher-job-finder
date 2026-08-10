"""演示种子数据。

全部为**演示数据**，与任何真实店铺、买家、订单或支付账户无关。
买家名使用明显虚构的标识；不写入任何真实邮箱或电话。

用法：uv run python -m app.seed
可重复执行：已存在同名租户时只补缺失数据，不重复插入。
"""

import json
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.models import Conversation, KnowledgeArticle, Order, Tenant, User
from app.routers.auth import ROLE_ADMIN, ROLE_AGENT, hash_password

# 演示语料随包放在 app/data/ 下，而不是仓库根目录：
# 根目录只留当前 V1 的入口与文档，避免看仓库的人误以为散落的文件是主程序。
KB_PATH = Path(__file__).resolve().parent / "data" / "kb_demo.json"
TENANT_SLUG = "demo-shop"

# 演示订单：订单号、平台、国家、金额、状态、物流概述、轨迹
DEMO_ORDERS = [
    (
        "#CB-20512",
        "Amazon",
        "美国",
        42.80,
        "在途",
        "洛杉矶 LAX 清关中",
        ["已揽收 · 深圳仓", "干线运输 · 深圳→洛杉矶", "清关完成 · LAX 海关", "末端派送中"],
    ),
    (
        "#CB-20485",
        "TikTok Shop",
        "印尼",
        18.00,
        "清关延误",
        "雅加达海关查验中",
        ["已揽收 · 广州仓", "到达雅加达", "清关延误 · 海关查验中", "待放行"],
    ),
    (
        "#CB-20477",
        "Shopify",
        "英国",
        61.30,
        "已退回",
        "派送失败，退回仓库",
        ["已揽收 · 义乌仓", "到达英国", "派送失败 · 地址有误", "已退回处理中"],
    ),
    ("#CB-20470", "Shopee", "加拿大", 33.20, "已签收", "已送达", []),
    (
        "#CB-20433",
        "Amazon",
        "美国",
        119.00,
        "运输中",
        "纽约分拣中心",
        ["已揽收 · 深圳仓", "抵达纽约分拣中心"],
    ),
]

# 演示会话：买家名刻意用虚构标识，不使用任何真实姓名
DEMO_CONVERSATIONS = [
    ("Buyer-A（演示）", "en", "#CB-20512"),
    ("Buyer-B（演示）", "id", "#CB-20485"),
    ("Buyer-C（演示）", "de", "#CB-20477"),
    ("Buyer-D（演示）", "zh", None),
]


def _seed_tenant(db: Session) -> Tenant:
    tenant = db.scalar(select(Tenant).where(Tenant.slug == TENANT_SLUG))
    if tenant is None:
        tenant = Tenant(name="演示店铺（Demo Shop）", slug=TENANT_SLUG)
        db.add(tenant)
        db.flush()
    return tenant


def _seed_users(db: Session, tenant: Tenant, password: str) -> None:
    for username, role in (("admin", ROLE_ADMIN), ("agent", ROLE_AGENT)):
        if db.scalar(select(User).where(User.username == username)) is None:
            db.add(
                User(
                    tenant_id=tenant.id,
                    username=username,
                    password_hash=hash_password(password),
                    role=role,
                    is_active=True,
                )
            )


def _seed_orders(db: Session, tenant: Tenant) -> None:
    for order_no, platform, country, amount, status, ship, steps in DEMO_ORDERS:
        exists = db.scalar(
            select(Order).where(Order.tenant_id == tenant.id, Order.order_no == order_no)
        )
        if exists is None:
            db.add(
                Order(
                    tenant_id=tenant.id,
                    order_no=order_no,
                    platform=platform,
                    country=country,
                    amount=amount,
                    currency="USD",
                    status=status,
                    shipping_summary=ship,
                    logistics_steps=steps,
                )
            )


def _seed_knowledge(db: Session, tenant: Tenant) -> int:
    """把演示语料导入 knowledge_articles（app/data/kb_demo.json）。"""
    if not KB_PATH.exists():
        return 0
    entries = json.loads(KB_PATH.read_text(encoding="utf-8")).get("entries", [])
    added = 0
    for e in entries:
        title = e.get("title", "")
        exists = db.scalar(
            select(KnowledgeArticle).where(
                KnowledgeArticle.tenant_id == tenant.id, KnowledgeArticle.title == title
            )
        )
        if exists is not None:
            continue
        db.add(
            KnowledgeArticle(
                tenant_id=tenant.id,
                title=title,
                body=e.get("text", ""),
                lang=e.get("lang", "zh"),
                keywords=e.get("keywords", []),
                is_active=True,
            )
        )
        added += 1
    return added


def _seed_conversations(db: Session, tenant: Tenant) -> None:
    for buyer, lang, order_no in DEMO_CONVERSATIONS:
        exists = db.scalar(
            select(Conversation).where(
                Conversation.tenant_id == tenant.id, Conversation.buyer_name == buyer
            )
        )
        if exists is not None:
            continue
        order = (
            db.scalar(select(Order).where(Order.tenant_id == tenant.id, Order.order_no == order_no))
            if order_no
            else None
        )
        db.add(
            Conversation(
                tenant_id=tenant.id,
                buyer_name=buyer,
                lang=lang,
                order_id=order.id if order else None,
                status="open",
            )
        )


def main() -> None:
    settings = get_settings()
    db = SessionLocal()
    try:
        tenant = _seed_tenant(db)
        _seed_users(db, tenant, settings.seed_password)
        _seed_orders(db, tenant)
        db.flush()
        kb_added = _seed_knowledge(db, tenant)
        db.flush()
        _seed_conversations(db, tenant)
        db.commit()

        def _count(model) -> int:
            return db.scalar(
                select(func.count()).select_from(model).where(model.tenant_id == tenant.id)
            )

        counts = {
            "orders": _count(Order),
            "knowledge_articles": _count(KnowledgeArticle),
            "conversations": _count(Conversation),
        }
        print(f"租户：{tenant.name}（slug={tenant.slug}）")
        print("演示账号：admin / agent，密码取自 SEED_PASSWORD（默认 demo1234）")
        print(f"本次新增知识条目：{kb_added}")
        print(f"当前数据量：{counts}")
        print("提示：以上均为演示数据，未接入真实店铺或支付平台。")
    finally:
        db.close()


if __name__ == "__main__":
    main()
