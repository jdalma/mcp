"""Lightweight question classification for vault decision advice."""

from __future__ import annotations

import re

FACT_LOOKUP_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"\bwhat\b|\bwhich\b|\blist\b|\bsummarize\b|\bshow\b",
        r"무엇|뭐가|어떤 .*있|목록|요약|정리|보여|알려",
        r"어디.*문서|where.*documented",
    ]
]

TRADEOFF_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"\bshould\b|\bchoose\b|\bselect\b|\badopt\b|\bvs\.?\b|\bversus\b",
        r"해야|할까|쓸까|써야|선택|채택|보류|아니면|대신|괜찮",
        r"strategy|architecture|policy|tradeoff|전략|설계|정책|방향",
    ]
]

IMPLEMENTATION_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"\bimplement\b|\brefactor\b|\bwhere should\b|\bhow should\b",
        r"구현|리팩터|수정|어떻게 .*할|어디에 .*넣",
    ]
]

DESTRUCTIVE_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        # 명령형/실행 의도가 분명한 동사만 매칭. 전략·설계 질문(예: "deploy 전략을 어떻게")은
        # tradeoff_decision으로 분류되도록 좁힌다.
        r"\bdelete\b|\bremove\b|\bdrop\b|\breset\b|\brollback\b",
        r"\b(deploy|push|merge|migrate)\s+(it|this|that|now|to|the)\b",
        r"\b(run|execute|apply)\s+(the\s+)?(migration|deploy|rollback)\b",
        r"삭제(해|할까|하자|하라|할게)|제거(해|할까|하자|하라)|드롭(해|할까)|리셋(해|할까)|초기화(해|할까)",
        r"롤백(해|할까|하자|하라)|푸시(해|할까|하자|하라)|머지(해|할까|하자|하라)",
        r"배포(해|할까|하자|하라|시작)|마이그레이션\s*(실행|시작|해|할까)",
    ]
]


def classify_question(question: str) -> str:
    """Return a conservative question type."""
    text = question.strip()
    if not text:
        return "unknown"

    if any(pattern.search(text) for pattern in DESTRUCTIVE_PATTERNS):
        return "destructive_action"
    if any(pattern.search(text) for pattern in TRADEOFF_PATTERNS):
        return "tradeoff_decision"
    if any(pattern.search(text) for pattern in IMPLEMENTATION_PATTERNS):
        return "implementation_guidance"
    if any(pattern.search(text) for pattern in FACT_LOOKUP_PATTERNS):
        return "fact_lookup"
    return "unknown"
