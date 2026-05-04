"""Tests for question classification."""


def test_classifies_tradeoff_decision():
    from classifier import classify_question

    assert classify_question("Kafka를 써야 할까 아니면 outbox만으로 충분할까?") == "tradeoff_decision"


def test_classifies_fact_lookup():
    from classifier import classify_question

    assert classify_question("Payment MSA 관련 Decision 목록 보여줘") == "fact_lookup"


def test_classifies_destructive_action_first():
    from classifier import classify_question

    assert classify_question("이 테이블을 drop 해도 될까?") == "destructive_action"
