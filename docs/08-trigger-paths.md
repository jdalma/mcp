# Vault Decision Gate 호출 경로

이 문서는 vault-decision MCP가 **언제, 어떤 방식으로 호출되는지**를 사용자 관점에서 정리한다. "내가 무슨 말을 하면 vault가 자동으로 조회되는가"를 알고 싶다면 이 문서만 읽으면 된다.

## 한눈에 보기

호출 경로는 3가지다.

| # | 경로 | 결정성 | 누가 트리거 | 사용자 가시성 |
|---|------|--------|-------------|--------------|
| 1 | **자동 — UserPromptSubmit 훅** | 정규식 결정적 | 훅이 메시지를 분류해서 자동 주입 | `[VAULT DECISION GATE]` system-reminder가 보임 |
| 2 | **명시 호출 — 사용자 의도** | 100% | 사용자가 직접 지시 | 모델이 MCP tool call을 띄움 |
| 3 | **자발 호출 — 모델 판단** | 모델 재량 | 모델이 맥락을 보고 스스로 호출 | 모델이 MCP tool call을 띄움 |

1번만 진짜 "GATE"이고, 2번과 3번은 모델이 직접 MCP 도구를 부르는 경로다.

---

## 1. 자동 호출 — UserPromptSubmit 훅

`~/.claude/hooks/user-prompt-submit/vault-decision-inject.mjs`가 매 사용자 메시지마다 실행된다. 다음 조건이 **모두** 만족되어야 GATE가 주입된다.

1. `VAULT_DECISION_GATE` 환경변수가 `false` 또는 `0`이 아님
2. 사용자 메시지가 비어있지 않음
3. **NON_DECISION 패턴**에 매칭되지 않음
4. **DECISION 패턴** 중 하나 이상에 매칭됨
5. MCP 서버(`127.0.0.1:8765`) 헬스체크 통과

조건이 만족되면 `additionalContext`로 `[VAULT DECISION GATE]` 블록이 주입되고, 모델은 그 지시에 따라 `mcp__vault-decision__advise`를 호출한 뒤 답변한다.

### 트리거되는 표현 (DECISION 패턴)

| 패턴 | 매칭 예시 |
|------|----------|
| 어떤/무엇을 + 써야/선택/사용 | "어떤 캐시를 써야 할까", "which framework to choose" |
| should / 할까 / 괜찮 / 맞나요 / appropriate / right | "이 방식이 적절할까", "should I split this" |
| approach / strategy / design / architecture / 전략 / 설계 / 방향 / 구현 | "outbox 설계 방향", "retry 전략 추천" |
| vs / 아니면 / versus | "Redis vs Memcached", "REST 아니면 gRPC" |
| 라이브러리/DB/패키지 + 추천/선택 | "어떤 database를 recommend", "패키지 선택 도와줘" |

### 트리거되지 않는 표현 (NON_DECISION 패턴 우선 차단)

의사결정처럼 보여도 다음 키워드가 들어가면 GATE가 뜨지 않는다.

| 차단 키워드 | 예시 |
|------------|------|
| 어떤 파일 / 이름 / 경로 / path | "어떤 파일을 수정?" |
| proceed / 진행 / 계속 | "계속 진행해도 될까" |
| format / style / 포맷 / 스타일 | "이 스타일 괜찮아?" |
| (delete\|삭제\|지워도) + (괜찮\|될까) | "이거 지워도 될까" |
| (modify\|수정\|고쳐도) + (괜찮\|될까) | "이거 고쳐도 될까" |
| commit / push / merge / 배포 / 커밋 / 푸시 | "지금 커밋해도 돼?" |
| 몇 개 / 얼마나 | "몇 개야?" |
| 어디 / 위치 | "이거 어디 있어?" |
| 언제 | "언제 추가됐어?" |
| 확인해 / 맞는지 | "이게 맞는지 확인해줘" |

### 테스트용 프롬프트

자동 호출이 동작하는지 확인하고 싶으면 다음을 그대로 던진다.

**✅ 트리거되어야 함**
```
Redis vs Memcached 뭐 쓸까
outbox 패턴 설계 방향 알려줘
어떤 메시지 브로커를 써야 할까
이 방식이 적절할까
어떤 database를 recommend
```

**❌ 트리거되지 않아야 함**
```
이 PR 머지해도 될까
이 파일 어디 있어
이 스타일 괜찮아
이거 지워도 될까
outbox 정책 알려줘            (의미상 의사결정이지만 정규식 미매칭)
```

### 자동 호출 성공 신호

다음 3가지가 모두 보이면 자동 호출이 정상 동작한 것이다.

1. 사용자 메시지 직후 `[VAULT DECISION GATE]`로 시작하는 `<system-reminder>` 박스
2. 모델이 `mcp__vault-decision__advise` 도구를 호출
3. 답변 첫머리에 `authority_level`, `recommended_action`, basis 파일명이 등장

박스가 안 뜨면 classifier가 의사결정으로 분류하지 않은 것이다.

---

## 2. 명시 호출 — 사용자가 직접 부르는 경우

GATE를 거치지 않고 사용자 의도가 분명할 때 모델이 바로 MCP 도구를 부른다.

| 사용자 표현 | 호출되는 도구 |
|------------|--------------|
| "vault에서 ~ 확인해줘", "vault 조회해줘" | `advise` |
| "advise 툴로 ~", "vault decision 검색" | `advise` |
| "ADR 찾아줘", "결정 문서 찾아줘" | `advise` 또는 `query` |
| "vault query로 ~ 검색" | `query` |
| "list_decisions로 최근 결정 보여줘" | `list_decisions` |
| "read_decision으로 'X.md' 읽어줘" | `read_decision` |
| "decision_timeline 보여줘" | `decision_timeline` |
| "vault stats 알려줘" | `stats` |
| "vault reindex 해줘" | `reindex` |

명시 호출은 GATE의 NON_DECISION 차단을 받지 않는다. "vault에서 머지 정책 확인해줘" 처럼 차단 키워드가 섞여 있어도 동작한다.

---

## 3. 자발 호출 — 모델이 스스로 호출

GATE도 안 뜨고 사용자가 명시하지도 않았는데 모델이 "이건 vault에 답이 있을 것 같다"고 판단해서 호출하는 경우다.

자발 호출이 일어나는 트리거:

- 세션 시작 시 vault-decision MCP 서버 instructions에 도구 사용 안내가 로드됨
- CLAUDE.md의 `Prefer evidence over assumptions` 원칙 적용
- 기존 결정과 충돌 가능성이 보이는 작업 (예: "outbox 통합하자" → 과거 분리 결정 의심)
- vault에서만 정의된 도메인 약어가 등장 (예: "B-2 표준 구조", "패턴 X/Y")
- classifier가 못 잡는 의사결정 표현 (예: "outbox 정책 알려줘")

**한계**: 자발 호출은 모델 재량이라 매번 100% 일관되지 않는다. 확실하게 부르려면 1번이나 2번 경로를 쓴다.

---

## 호출이 차단/스킵되는 경우

| 상황 | 영향받는 경로 |
|------|--------------|
| `VAULT_DECISION_GATE=false` 환경변수 | 1번만 차단 |
| MCP 서버(8765) 다운 | 1번 스킵, 2·3번은 호출 시 에러 |
| NON_DECISION 패턴 매칭 | 1번만 차단 (2번 명시 호출은 가능) |
| 빈 메시지 / 페이로드 파싱 실패 | 1번 스킵 |

---

## FAQ

**Q. "outbox 정책 알려줘"는 왜 자동으로 안 뜨나요?**
DECISION 정규식에 매칭되는 키워드가 없기 때문이다. 의미상 의사결정이지만 classifier는 단순 정규식이라 의도를 못 읽는다. "outbox 정책 어떻게 가야 할까"처럼 `할까`를 붙이거나, "vault에서 outbox 정책 찾아줘"로 명시 호출하면 된다.

**Q. 자동 호출을 더 자주 일으키고 싶어요.**
프로젝트 CLAUDE.md에 한 줄 추가한다.
```
의사결정·설계·트레이드오프 질문이 조금이라도 의심되면
mcp__vault-decision__advise를 먼저 호출한 뒤 답한다.
```
트레이드오프: 단순 코딩 질문에도 vault 조회가 끼어들어 응답이 약간 느려진다.

**Q. 자동 호출을 끄고 싶어요.**
환경변수로 끈다.
```bash
export VAULT_DECISION_GATE=false
```

**Q. 패턴을 수정하려면 어디를 보면 되나요?**
`~/.claude/hooks/shared/vault-decision-patterns.mjs`의 `DECISION_PATTERNS` / `NON_DECISION_PATTERNS` 배열.

---

## 부록: 훅이 컨텍스트를 자동 주입하는 전체 맥락

vault GATE는 여러 훅 중 하나일 뿐이다. Claude Code는 사용자 메시지와 도구 호출 시점마다 훅을 실행해 모델 컨텍스트에 추가 지시를 주입한다. vault 호출 동작을 정확히 이해하려면 이 전체 그림이 필요하다.

### 주입되는 훅 종류

| 훅 이벤트 | 트리거 시점 | 주입 예시 | vault 호출에 미치는 영향 |
|----------|-----------|---------|------------------------|
| **SessionStart** | 세션 시작 시 1회 | superpowers 스킬, MCP 서버 instructions | 모델에게 vault-decision MCP의 **존재**를 알림 (자발 호출의 전제) |
| **UserPromptSubmit** | 사용자 메시지마다 | `[VAULT DECISION GATE]` 블록 (조건부) | 자동 호출(1️⃣)을 강제 — 핵심 트리거 |
| **PreToolUse** | 도구 호출 직전 | "Use parallel execution...", "Verify changes..." | vault 호출 결정에는 영향 없음 (도구 실행 시점 메시지) |
| **PostToolUse** | 도구 호출 직후 | "File written. Test the changes..." | vault 호출 결정에는 영향 없음 |
| **주기적 reminder** | 일정 주기 | TaskCreate 사용 권장 등 | 영향 없음 |

### 관찰 신호

훅이 주입한 컨텍스트는 사용자 화면에 다음과 같이 나타난다.

```
[VAULT DECISION GATE]                              ← UserPromptSubmit 주입
이 질문은 의사결정과 관련이 있다.
응답 전에 반드시 mcp__vault-decision__advise...

UserPromptSubmit hook success: OK                  ← 훅 실행 완료 신호
PreToolUse:Bash hook additional context: ...       ← 도구 직전 주입
PostToolUse:Write hook additional context: ...     ← 도구 직후 주입
```

`hook success: OK` 또는 `hook additional context:` 라인이 보이면 그게 자동 삽입의 실시간 증거다.

### vault 호출 경로별 훅 의존도

| 경로 | 필요한 훅 |
|------|----------|
| 1️⃣ 자동 (GATE) | UserPromptSubmit (`vault-decision-inject.mjs`) — 필수 |
| 2️⃣ 명시 호출 | SessionStart (MCP 등록) — 필수, GATE 훅 불필요 |
| 3️⃣ 자발 호출 | SessionStart (MCP instructions 로드) — 필수, GATE 훅 불필요 |

→ **MCP 서버가 등록되지 않으면 세 경로 모두 동작 불가**. GATE 훅이 "advise를 호출하라"고 지시해도 모델에 그 도구가 없으면 호출할 방법이 없다.

### 훅 출력 제어

| 환경변수 | 효과 |
|---------|------|
| `VAULT_DECISION_GATE=false` | GATE 훅만 비활성화 (1️⃣ 차단, 2️⃣·3️⃣은 동작) |
| `OMC_SKIP_HOOKS=vault-decision-inject` | 특정 훅만 스킵 (comma-separated) |
| `DISABLE_OMC=1` | OMC 훅 전체 비활성화 |

### 훅 등록 위치

```
~/.claude/settings.json                                    ← 훅 등록 정의
~/.claude/hooks/user-prompt-submit/vault-decision-inject.mjs  ← GATE 훅 본체
~/.claude/hooks/shared/vault-decision-patterns.mjs            ← DECISION/NON_DECISION 정규식
```

훅 동작이 의심스러우면 위 세 파일을 직접 읽어 확인한다.

---

## 한 줄 요약

자동 호출은 정규식이 잡는 의사결정 표현에만 동작한다. 확실하게 vault를 보고 싶으면 "vault에서" 한마디만 붙이면 된다.
