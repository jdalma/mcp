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


def test_deploy_strategy_question_is_not_destructive():
    """'deploy 전략' 같은 tradeoff 질문이 destructive로 오분류되지 않아야 함."""
    from classifier import classify_question

    assert classify_question("배포 전략을 어떻게 세워야 할까?") == "tradeoff_decision"
    assert classify_question("Which deploy strategy should we adopt?") == "tradeoff_decision"


def test_imperative_destructive_still_caught():
    """명령형 파괴 동사는 여전히 destructive로 잡혀야 함."""
    from classifier import classify_question

    assert classify_question("지금 배포해줘") == "destructive_action"
    assert classify_question("롤백하자") == "destructive_action"
    assert classify_question("Run the migration now") == "destructive_action"
