"""订阅规则接口（已实现 CRUD）。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from deps import get_current_user
from models import User, SubRule
from schemas import RuleIn, RuleOut

router = APIRouter(prefix="/rules", tags=["rules"])


@router.get("", response_model=list[RuleOut])
def list_rules(user: User = Depends(get_current_user)):
    return user.rules


@router.post("", response_model=RuleOut)
def create_rule(
    body: RuleIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rule = SubRule(user_id=user.id, **body.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.put("/{rule_id}", response_model=RuleOut)
def update_rule(
    rule_id: str,
    body: RuleIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rule = db.get(SubRule, rule_id)
    if rule is None or rule.user_id != user.id:
        raise HTTPException(404, "规则不存在")
    for k, v in body.model_dump().items():
        setattr(rule, k, v)
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/{rule_id}")
def delete_rule(
    rule_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rule = db.get(SubRule, rule_id)
    if rule is None or rule.user_id != user.id:
        raise HTTPException(404, "规则不存在")
    db.delete(rule)
    db.commit()
    return {"ok": True}
