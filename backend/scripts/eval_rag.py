"""RAG 检索质量评测。

为什么需要：光看几个例子说"效果不错"是没有说服力的，
改了检索逻辑（换 embedding、调阈值、改扩展策略）之后，
也无从判断是变好还是变坏。这里给出可复跑、出数字的基线。

指标：
- 召回率        有多少题至少检索到一条片段（零召回是最糟的失败）
- P@1 / P@3     top-1 / top-3 里是否命中含答案的片段
- 拒答正确率    语料里确实没有的问题，是否正确拒答

用法：
    python scripts/eval_rag.py                 # 完整评测
    python scripts/eval_rag.py --no-expand     # 关掉查询扩展做对照

注意：带 --with-llm 才会真调模型生成答案（花钱）；
默认只评检索层，因为检索错了答案一定错，先把检索这层量化住。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database import SessionLocal
from services import llm_credentials, rag_qa

# 每题给出"含答案的片段里必然出现的词"。
# 用关键词而非精确答案，是因为语料会随爬虫更新，
# 绑死具体答案会让评测集很快失效。
ANSWERABLE = [
    ("报名需要提交哪些材料？", ["材料", "证", "报名表"]),
    ("要交什么东西？", ["材料", "证", "提交"]),
    ("对学历有什么要求？", ["学历", "本科", "研究生"]),
    ("本科能报吗？", ["本科", "学历"]),
    ("需要教师资格证吗？", ["教师资格"]),
    ("普通话要几级？", ["普通话"]),
    ("年龄有限制吗？", ["岁", "年龄"]),
    ("有编制吗？", ["编制", "事业单位"]),
    ("工资多少？", ["薪", "待遇", "万", "元"]),
    ("笔试考什么？", ["笔试", "科目", "内容"]),
    ("要不要笔试？", ["笔试"]),
    ("面试怎么进行？", ["面试"]),
    ("入围面试的比例是多少？", ["比例", "倍", "1:"]),
    ("资格复审是怎么回事？", ["资格复审", "复审"]),
    ("什么时候体检？", ["体检"]),
    ("什么时候出结果？", ["公示", "公布"]),
    ("考察阶段看什么？", ["考察"]),
    ("违纪会怎么处理？", ["违纪", "取消"]),
    ("聘用后有培训吗？", ["培训"]),
    ("考核不合格怎么办？", ["考核"]),
]

# 语料里确实没有的信息——正确行为是拒答而不是硬凑。
# 这几条守的是防幻觉这条红线。
UNANSWERABLE = [
    "可以远程办公吗？",
    "有没有股票期权？",
    "公司团建去哪里？",
    "能带宠物上班吗？",
]


def evaluate(expand: bool, cred=None) -> dict:
    """cred 不给时用 stub 凭据：评测默认只量化检索层，不花钱调模型。

    要评真实模型答案时传一个真实用户的凭据（配合 --with-llm）。
    """
    cred = cred or llm_credentials.stub_credential()
    db = SessionLocal()
    try:
        recalled = p1 = p3 = 0
        zero_recall = []
        for question, must in ANSWERABLE:
            chunks = rag_qa.retrieve(db, question, k=3, expand=expand, cred=cred)
            if not chunks:
                zero_recall.append(question)
                continue
            recalled += 1
            if any(m in chunks[0].content for m in must):
                p1 += 1
            if any(any(m in c.content for m in must) for c in chunks):
                p3 += 1

        refused = 0
        wrongly_answered = []
        for question in UNANSWERABLE:
            result = rag_qa.ask(db, question, k=3, cred=cred)
            if not result["found"] or "未提及" in result["answer"]:
                refused += 1
            else:
                wrongly_answered.append(question)
    finally:
        db.close()

    n, m = len(ANSWERABLE), len(UNANSWERABLE)
    return {
        "expand": expand,
        "answerable": n,
        "recall": round(recalled / n, 3),
        "p_at_1": round(p1 / n, 3),
        "p_at_3": round(p3 / n, 3),
        "zero_recall_questions": zero_recall,
        "unanswerable": m,
        "refusal_rate": round(refused / m, 3),
        "wrongly_answered": wrongly_answered,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate RAG retrieval quality.")
    parser.add_argument("--no-expand", action="store_true",
                        help="关掉查询扩展，用于做前后对照")
    parser.add_argument("--json", action="store_true", help="只输出 JSON")
    args = parser.parse_args()

    result = evaluate(expand=not args.no_expand)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"RAG 检索评测（查询扩展：{'开' if result['expand'] else '关'}）")
    print(f"  有答案的题 {result['answerable']} 道")
    print(f"    召回率  {result['recall']:.0%}")
    print(f"    P@1     {result['p_at_1']:.0%}")
    print(f"    P@3     {result['p_at_3']:.0%}")
    if result["zero_recall_questions"]:
        print(f"    零召回：{'、'.join(result['zero_recall_questions'])}")
    print(f"  语料没有的题 {result['unanswerable']} 道")
    print(f"    正确拒答率 {result['refusal_rate']:.0%}")
    if result["wrongly_answered"]:
        print(f"    不该答却答了：{'、'.join(result['wrongly_answered'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
