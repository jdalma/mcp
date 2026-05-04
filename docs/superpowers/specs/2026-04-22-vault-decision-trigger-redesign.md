# Vault Decision Trigger Redesign

**Date:** 2026-04-22  
**Status:** Draft — Pending Review  
**Context:** vault-decision-mcp, `~/.claude/hooks/pre-tool-use.mjs`

---

## 1. 문제 진단

### 현재 구현

`PreToolUse` 훅이 `AskUserQuestion` tool 호출을 가로채서 vault 조회를 강제한다.

```
사용자 메시지 → Claude 처리 → AskUserQuestion 호출
                                    ↑ 여기서만 개입 가능
```

### 실효성 측정

vault-decision MCP 서버 실행 기간 동안 `~/.vault-decision-mcp/calls.jsonl` 호출 이력: **0건**

이것은 Claude Code가 `AskUserQuestion` tool을 실질적으로 사용하지 않기 때문이다. Claude는 텍스트 응답으로 직접 질문하는 방식을 선택한다. 훅이 트리거되려면 Claude가 특정 tool을 호출해야 하는데, 그 tool이 호출되지 않으므로 훅은 사실상 무용지물이다.

### 실패 모드 분류

| 경로 | 현재 훅 개입 여부 |
|------|-----------------|
| Claude가 텍스트로 "A와 B 중 어떤 방식이 좋을까요?" 응답 | **불가** |
| Claude가 `AskUserQuestion` tool 호출 | 가능 (but 발생 빈도 ≈ 0) |
| Claude가 즉시 결정을 내리고 구현 진행 | **불가** |
| 사용자가 의사결정 질문을 입력 | **불가** |

핵심: **vault 조회가 필요한 시점은 Claude가 응답을 생성하기 직전이 아니라, 사용자가 질문을 제출한 직후**다.

---

## 2. 대안 비교

### 대안 A: CLAUDE.md 강화 (명령형 지시)

CLAUDE.md에 "의사결정 질문 시 항상 vault query tool을 먼저 호출하라"를 추가한다.

**장점**
- 구현 비용 없음
- 훅 복잡도 증가 없음

**단점**
- Claude가 지시를 무시할 확률 높음 (특히 대화 중반 이후)
- 컨텍스트 압축 후 망각 가능
- 측정/검증 불가

**적합 상황**: 즉시 테스트 목적, 또는 다른 대안의 보완책

---

### 대안 B: UserPromptSubmit always-inject

`UserPromptSubmit` 훅에서 **매 턴** vault query 지시를 `additionalContext`로 주입한다.

```
사용자 메시지 제출
      ↓
UserPromptSubmit 훅 실행
      ↓
additionalContext 주입: "의사결정 질문이면 vault 먼저 조회하라"
      ↓
Claude 처리 (주입된 컨텍스트 포함)
```

**장점**
- 훅 개입 시점이 올바름 (Claude 처리 직전)
- 구현 단순 (조건 분기 없이 항상 주입)
- openclone 패턴으로 검증된 방식

**단점**
- 모든 메시지에 컨텍스트가 추가되어 token 비용 증가
- 의사결정과 무관한 질문에도 불필요한 지시가 포함됨
- Claude가 context noise로 간주하고 무시할 수 있음

**적합 상황**: vault 조회 누락이 치명적인 경우

---

### 대안 C: UserPromptSubmit 조건부 inject (권장)

`UserPromptSubmit` 훅에서 메시지를 분석하여 의사결정 질문일 때만 `additionalContext`를 주입한다.

```
사용자 메시지 제출
      ↓
UserPromptSubmit 훅: isDecisionQuestion() 판별
      ├─ Yes → additionalContext 주입 후 Claude 처리
      └─ No  → 그냥 통과
```

**장점**
- 훅 개입 시점 올바름
- 불필요한 token 낭비 없음
- 기존 `DECISION_PATTERNS` regex 재활용 가능
- 사용자 메시지 전체 텍스트로 판별 → PreToolUse보다 판별 정확도 높음

**단점**
- 패턴 매칭 정확도에 의존 (false negative 가능)
- 훅 스크립트 추가 구현 필요

**적합 상황**: 이 설계의 권장 방향

---

### 대안 D: Stop + UserPromptSubmit 2단계

- `Stop` 훅: Claude 응답에서 의사결정 상황 감지 → 다음 턴 플래그 기록
- `UserPromptSubmit` 훅: 플래그가 있으면 다음 사용자 메시지에 vault 조회 지시 주입

**장점**
- Claude의 실제 응답 텍스트 기반으로 판별 → 높은 정확도 이론상 가능

**단점**
- Stop 훅은 응답이 이미 사용자에게 전달된 후 실행 → 해당 턴 차단 불가
- 1턴 지연: 이미 내린 결정을 다음 턴에야 vault 조회 가능
- 구현 복잡도 높음 (상태 파일 관리, 경쟁 조건)
- 효과가 "사후 교정"에 가까워 실질적 의사결정 품질 개선 불확실

**적합 상황**: 권장하지 않음

---

## 3. 권장 구현: 대안 C

### 구현 순서 (의존성 명시)

단계 간 선후관계가 있으므로 순서를 지켜야 한다:

1. **UserPromptSubmit 입력 스키마 확인** — `data.user_message` 키 검증
2. **판별 로직 공통 모듈 추출** — `pre-tool-use.mjs`의 `isDecisionQuestion()` / `DECISION_PATTERNS`를 `~/.claude/hooks/shared/vault-decision-patterns.mjs`로 분리
3. **새 훅 파일 구현** — `vault-decision-inject.mjs` 작성 (헬스체크 포함)
4. **settings.json 등록** — `UserPromptSubmit` 배열에 추가
5. **동작 검증** — 의사결정 질문 입력 후 `calls.jsonl` 기록 확인
6. **기존 PreToolUse gate 제거** — 5단계 검증 완료 후에만 제거 (공백 기간 방지)
7. **관측 기간 운영** — 1주 간 `calls.jsonl` 및 오탐율 모니터링

### 구현 위치

새 파일: `~/.claude/hooks/user-prompt-submit/vault-decision-inject.mjs`

`~/.claude/settings.json` 등록:

```json
"UserPromptSubmit": [
  {
    "hooks": [
      {"type": "command", "command": "node ~/.claude/hooks/keyword-detector.mjs"},
      {"type": "command", "command": "node ~/.claude/hooks/user-prompt-submit/vault-decision-inject.mjs"}
    ]
  }
]
```

`keyword-detector.mjs`와 `vault-decision-inject.mjs`는 각각 독립적으로 stdout을 출력하며 상호 의존이 없다. Claude Code는 배열 순서대로 실행하고 각 훅의 `additionalContext`를 독립적으로 병합한다.

### MCP 서버 헬스체크

`/health` 엔드포인트가 없으므로 TCP 연결 가능 여부로 확인한다. `nc -z 127.0.0.1 8765`가 exit code 0이면 서버 가동 중, 1이면 다운. 서버가 다운된 경우 `additionalContext` 주입 자체를 건너뛴다 (불필요한 지시 및 Claude의 tool 호출 실패 왕복 방지).

### 핵심 로직

```js
// vault-decision-inject.mjs
import { readFileSync } from 'fs';
import { execSync } from 'child_process';
import { isDecisionQuestion } from '../shared/vault-decision-patterns.mjs';

const data = JSON.parse(readFileSync('/dev/stdin', 'utf8'));
const userMessage = data.user_message || data.message || '';

const suppress = JSON.stringify({ continue: true, suppressOutput: true });

if (!isDecisionQuestion(userMessage)) {
  process.stdout.write(suppress);
  process.exit(0);
}

// 헬스체크: 서버 다운 시 주입 스킵
try {
  execSync('nc -z 127.0.0.1 8765', { stdio: 'ignore', timeout: 500 });
} catch {
  process.stdout.write(suppress);
  process.exit(0);
}

process.stdout.write(JSON.stringify({
  continue: true,
  hookSpecificOutput: {
    hookEventName: 'UserPromptSubmit',
    additionalContext: [
      '[VAULT DECISION GATE]',
      '이 질문은 의사결정과 관련이 있다.',
      '응답 전에 반드시 mcp__vault-decision__query tool로 vault를 조회하라.',
      `  question: "${userMessage.slice(0, 200)}"`,
      '조회 결과를 바탕으로 답변에 관련 Decision 파일명을 명시하라.',
      '관련 기록이 없으면 없다고 명시하고 진행하라.',
    ].join('\n'),
  },
}));
```

### 기존 PreToolUse 훅 처리

구현 순서 6단계 — UserPromptSubmit 동작 검증 완료 후 `AskUserQuestion` gate를 제거한다. 검증 전 제거 시 두 훅 모두 없는 공백 기간이 발생한다.

---

## 4. 성공 측정 기준

| 지표 | 기준 |
|------|------|
| `calls.jsonl` query 건수 | 구현 후 1주 내 5건 이상 기록 |
| 의사결정 답변 내 Decision 참조 | 관련 기록 있을 때 ≥ 70% 인용 |
| 오탐율 (비결정 질문에 주입) | ≤ 20% (수동 샘플 확인) |

---

## 5. 한계 및 미해결 사항

- **패턴 매칭 한계**: `DECISION_PATTERNS` regex는 한국어+영어 혼합 의도를 완전히 커버하지 못한다. LLM 기반 분류기로 대체 가능하지만 훅 응답 시간이 늘어난다.
- **vault 서버 가용성**: vault-decision MCP 서버(port 8765)가 꺼져 있으면 Claude가 tool 호출에 실패한다. additionalContext 주입 전 서버 헬스체크를 추가하면 불필요한 지시를 억제할 수 있다.
- **컨텍스트 우선순위**: Claude가 additionalContext를 무시할 가능성은 여전히 존재한다. 이는 훅 기반 접근의 근본적 한계다.
