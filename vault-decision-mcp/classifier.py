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
        r"\bdelete\b|\bremove\b|\bdrop\b|\breset\b|\bdeploy\b|\bmigrate\b|\brollback\b|\bpush\b|\bmerge\b",
        r"삭제|제거|드롭|리셋|초기화|배포|마이그레이션|롤백|푸시|머지",
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
