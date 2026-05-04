# 06. Decision 생명주기와 운영

Decision 문서가 어떻게 태어나고 살다가 폐기되는지, 그리고 사람이 언제 어떻게 개입해야 하는지 정리한다.

## 핵심 원칙

> **파일을 지우거나 옮기지 말고, 권한 메타만 바꿔라.**

시스템은 stale/superseded 결정도 검색에는 잡고 권한만 약화시킨다. 즉 "이 결정은 한때 이랬다"는 역사가 남아야 미래에 같은 실수를 안 하고, `historical_negative` 신호로 작동한다.

## Decision의 일생 (5단계)

```
① 후보 단계 (note)
        ↓ 결정 확정
② FRESH (decided_applicable) ★
        ↓ revisit_when 도래 또는 status 변경
③ STALE (decided_stale)
        ↓ 사람의 재평가
④ 재평가 시점 (사람 수동)
        ↓ 또는
⑤ 폐기 (decision_status: superseded/deprecated/retired)
        ↓
   99 Archive로 이동 (선택)
   → historical_negative 신호
```

### ① 후보 단계 (note)

```yaml
type: note
status: hypothesis
decision_candidates:
  - "Option A: ..."
  - "Option B: ..."
```

→ `candidate` 버킷, `ask_confirmation` 권고. "후보는 정리됐지만 아직 결정 전" 상태.

### ② FRESH ★

```yaml
type: decision
status: decided
decided_on: 2026-04-16
revisit_when: 2026-08-01
decision_status: ""
conflicts_with: ""
```

→ `decided_applicable`, `proceed_candidate`. 이 결정 범위 안이라면 사용자에게 묻지 않고 진행.

### ③ STALE

다음 중 하나라도 발생:
- `revisit_when`의 날짜가 오늘 ≤ 도래
- `status`가 `decided`에서 다른 값으로 바뀜
- `decision_status`에 `superseded`/`deprecated`/`retired` 중 하나가 적힘

→ `decided_stale`, `ask_confirmation`. 검색엔 잡히지만 "재확인 필요"로 표시.

### ④ 재평가 시점

사람이 결정해야 하는 단계. 시스템은 자동으로 처리 안 함.

선택지 3가지:
- **여전히 유효** → ②로 복귀, `revisit_when` 갱신
- **폐기** → ⑤로
- **새 결정으로 대체** → 새 Decision 작성, 옛 결정은 ⑤로

### ⑤ 폐기

```yaml
decision_status: superseded   # 또는 deprecated, retired
updated: 2026-05-04
```

검색엔 잡히지만 stale로만 보이고 진행 권고 안 됨. `99 Archive/`로 이동하면 `historical_negative` 신호로 작동.

## 자동 만료 메커니즘

### `_is_stale_decision`이 stale 판정하는 3가지 트리거

`advisor.py:62-74`:

```python
def _is_stale_decision(meta, current_date=None) -> bool:
    decision_status = str(meta.get("decision_status", "")).lower()
    if decision_status in {"superseded", "deprecated", "retired"}:
        return True

    if str(meta.get("status", "")).lower() != "decided":
        return True

    due_date = _parse_due_date(str(meta.get("revisit_when", "")))
    if due_date and due_date <= (current_date or date.today()):
        return True

    return False
```

OR 조건. 하나라도 걸리면 stale.

| # | 트리거 | 의미 |
|---|---|---|
| 1 | `decision_status` 명시 | 사람이 직접 사망 선고 |
| 2 | `status ≠ decided` | 확정 안 됨 (애초에 fresh 자격 없음) |
| 3 | `revisit_when` 날짜 도래 | 시한부 만료 |

### `revisit_when`의 자동 만료 기준

```python
DATE_PATTERN = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
```

작동 조건 3개 모두 충족:
1. 텍스트 어딘가에 `20XX-XX-XX` 패턴 (4자리 연도 + 0 패딩 필수)
2. `date.fromisoformat()`이 파싱 가능
3. 추출 날짜 ≤ 오늘

매칭 동작:
- `re.search`로 첫 번째 매칭만 사용
- 텍스트 어디에 있든 추출
- 형식 외 텍스트는 모두 무시

```yaml
# ✅ 자동 만료 작동
revisit_when: "2026-08-01"
revisit_when: "vault 300노트 도달 시 또는 2026-12-31"
revisit_when: "2026-04-01 / 50개 도달 시"   # 첫 날짜만 추출

# ❌ 자동 만료 작동 안 함
revisit_when: "MCP 운영 2-4주 후"
revisit_when: "2026/08/01"        # 슬래시 안 됨
revisit_when: "2026-8-1"          # 0 패딩 필요
revisit_when: "buildv2026-08-01"  # \b 경계 깨짐
```

### stale 판정 후 일어나는 일

1. **버킷 분리**: `fresh_decisions`에서 빠지고 `stale_decisions`로 이동
2. **권한 레벨**:
   - fresh가 하나도 없고 stale만 있으면 → `decided_stale`
   - fresh가 같이 있으면 → fresh 우선, stale은 `supporting_evidence`로 강등
3. **추천 행동**: `proceed_candidate` → `ask_confirmation`
4. **warnings 추가**: `"Relevant Decision exists but may be stale or superseded."`

→ stale 판정은 **삭제하지 않고 권한만 약화**시키는 메커니즘.

## 사람이 개입해야 할 시점

### (A) 시스템이 자동으로 알려주는 신호 — 즉시 개입

| 신호 | 의미 | 어디서 |
|---|---|---|
| `decided_stale` | revisit_when 도래 또는 status 변경 | advise() 응답 authority_level |
| `decided_conflicting` | 두 fresh decision의 conflicts_with 매칭 | warnings: "Conflicting relevant Decisions detected" |
| 동일 주제 fresh decision 2개+ | 범위 분리 안 됨 | warnings: "Multiple relevant Decisions found" |
| `historical_negative` 동반 | Archive에 폐기 흔적과 함께 | warnings: "Archive contains historical negative" |

### (B) 정기 점검에서 발견하는 신호

| 발견 | 개입 시점 |
|---|---|
| 6개월+ 갱신 안 된 fresh decision | 분기 1회 점검 |
| revisit_when에 절대 날짜 없는 결정 | 결정 작성 시 또는 1차 점검 시 |
| 새 결정이 옛 결정과 모순 | 새 결정 작성 직후 |
| 외부 환경 변화 (팀 규모/규제/기술 스택) | 변화 발생 시점 |

### (C) 결정의 전제가 무너졌을 때

`revisit_when`에 적힌 사건 트리거가 발생:
- "vault 300노트 도달", "MAU 10만 돌파", "패턴 X 혼선 반복"
- 자동 감지 안 됨 → 운영 중 발견 시 즉시 개입

## 개입 패턴 5가지

### 패턴 1 — 결정이 여전히 유효함 (재확인)

stale 판정 났지만 검토해보니 그대로 유효.

```yaml
updated: 2026-05-04
revisit_when: 2026-12-01       # 새 절대 날짜
```

본문에 `## Reaffirmed (2026-05-04)` 한 줄 남기면 추적 가능.

### 패턴 2 — 결정이 폐기됨 (대체 없음)

더 이상 적용 안 하지만 새 결정도 없음.

```yaml
status: decided                  # 그대로
decision_status: retired         # 또는 deprecated
updated: 2026-05-04
```

본문에 `## Retired - Reason` 섹션 추가.

### 패턴 3 — 다른 결정으로 대체됨 (가장 흔함)

```yaml
# 옛 결정 파일
decision_status: superseded
updated: 2026-05-04
# 본문:
## Superseded by
[[Decision - 새 결정 제목]]
```

```yaml
# 새 결정 파일
type: decision
status: decided
decided_on: 2026-05-04
revisit_when: 2026-12-01
# 본문:
## Supersedes
[[Decision - 옛 결정 제목]]
```

→ 옛 결정은 stale, 새 결정만 fresh. 옛 결정 본문의 링크로 Claude가 자연스럽게 새 결정으로 이동.

### 패턴 4 — 두 결정이 충돌함

```yaml
# 두 파일 모두에 추가
conflicts_with: "Decision - 다른 결정 제목"
```

→ `decided_conflicting` → 사용자에게 escalate 강제. **충돌 자체가 결정 사항** — 어느 쪽이 맞는지 결정한 뒤 패턴 3으로 정리.

> 권장: 양쪽 결정에 모두 `conflicts_with`를 명시한다. 한쪽만 적으면 그쪽 결정이 검색에 잡힐 때만 conflict가 감지되므로 비대칭 위험이 있다.

### 패턴 5 — Archive로 보내기 (역사 신호로만 보존)

결정의 의미조차 더 이상 없을 때 (사라진 시스템에 대한 결정 등).

```bash
mv "01 Notes/Decision - 옛것.md" "99 Archive/"
```

→ `path_role=archive` + 본문에 폐기/대체 키워드 → `historical_negative` 신호. Claude가 검색하면 "이 방향은 거부됐던 적이 있다"로 인식하고 진행 거부.

## 결정 유형별 권장 갱신 주기

| 결정 유형 | 권장 패턴 | 예시 |
|---|---|---|
| 단기 임시방편 | `revisit_when`: 3개월 내 절대 날짜 | "비동기 처리 임시 비활성화 — 2026-08-01" |
| 분기성 결정 | `revisit_when`: 분기말 + 자유 텍스트 | "OKR 회고 시 / 2026-09-30" |
| 영구적 아키텍처 | 자유 텍스트 + 안전장치 1년 후 날짜 | "조회 패턴 변화 시 / 2027-05-04" |
| 정책/원칙 | 자유 텍스트만 | "이 정책의 전제가 무너지면" |

→ **모든 결정에 1년 후 안전장치 날짜를 박아두는 게 실용적**. 1년 후 자동 stale → 사람이 한 번 훑어본다.

## 정기 vault 점검 루틴

| 주기 | 작업 | 도구 |
|---|---|---|
| 매주 | 새 결정 작성 시 충돌 검사 | `query` 또는 `advise` |
| 매월 | stale 결정 목록 훑기 | `decision_timeline` |
| 분기 | conflict/multiple 경고 정리 | `stats` + `list_decisions` |
| 반기 | 1년 안 갱신된 결정 일괄 점검 | `decision_timeline` |

## 안티패턴 (절대 하지 말 것)

| 안티패턴 | 왜 안 되는가 |
|---|---|
| 폐기 결정 파일 삭제 | `historical_negative` 신호 손실 → 같은 실수 반복 |
| 옛 결정 본문을 새 내용으로 덮어쓰기 | 의사결정 이력 사라짐, `decided_on` 의미 깨짐 |
| `revisit_when` 무한 미래로 밀기 | 자동 만료 무력화, 결정이 영원히 안 검토됨 |
| `decision_status` 비우고 본문에만 "폐기됨" 적기 | MCP가 못 읽음 → 여전히 fresh로 추천 |
| 새 결정 작성 시 옛 결정 superseded 표시 누락 | `decided_conflicting` 양산 |

## 결정 폐기 체크리스트

새 결정이 옛 결정을 대체할 때:

```
□ 옛 결정에 decision_status: superseded 추가
□ 옛 결정 본문에 "## Superseded by [[새 결정]]" 추가
□ 옛 결정 updated 날짜 갱신
□ 새 결정 본문에 "## Supersedes [[옛 결정]]" 추가
□ 두 결정이 conflicts_with 관계라면 양쪽 명시
□ 옛 결정의 mocs/tags가 여전히 맞는지 확인
□ advise()를 다시 던져 새 결정만 fresh로 잡히는지 검증
```

마지막 단계가 중요 — vault 메타를 바꿔도 ChromaDB 인덱스는 watcher가 5초 디바운스로 갱신하므로, 즉시 검증하려면 `reindex` 도구를 한 번 호출.

## 트리거와 주기 정리

### 🤖 시스템 자동 (필드를 바꾸진 않음, 판정만 바뀜)

| 트리거 | 결과 | 주기 |
|---|---|---|
| 매 검색마다 (advise/query 호출 시) | revisit_when 평가 | 호출 시점 |
| 파일 저장 (watcher 5초 디바운스) | mtime 갱신, 재인덱싱 | 변경 후 5초 |
| 서버 재시작 | 전체 인덱스 검증, 누락분 동기화 | 시작 시 |

### ✋ 사람 수동 (필드 값을 바꿈)

| 작업 | 바꾸는 필드 | 주기 |
|---|---|---|
| 새 결정 작성 | type, status, decided_on, revisit_when | 결정 시점 |
| 결정 갱신/연장 | updated, revisit_when | 재평가 시 |
| 결정 폐기 | decision_status | 폐기 결정 시 |
| 결정 충돌 표시 | conflicts_with | 충돌 발견 시 |
| 폴더 이동 | (path_role 자동 변경) | 폐기 정리 시 |

## 한 줄 요약

**결정은 "지우는 것"이 아니라 "권한을 박탈하는 것".**
`revisit_when` 날짜 도래 → 자동 stale (시스템이 알려줌),
`decision_status` 변경 → 명시적 폐기 (사람이 선언),
파일은 남기고 메타만 바꾼다 — vault가 곧 의사결정 역사 자체이기 때문.
