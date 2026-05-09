# 03. frontmatter 필드 레퍼런스

`indexer.py:prepare_document`와 `advisor.py`에서 실제로 읽는 모든 필드를 정리한다.

## 필드 빠른 참조

| 필드 | 타입 | 영향 |
|---|---|---|
| `type` | enum | 부스팅 + 버킷 1차 키 |
| `status` | enum | 부스팅 + stale 판정 |
| `decision_status` | enum (decision 전용) | stale 판정 (사망 선고) |
| `revisit_when` | 자유 텍스트 + 날짜 | stale 자동 만료 트리거 |
| `decided_on` | 날짜 | timeline 정렬 키 |
| `created`, `updated` | 날짜 | 표시용 |
| `conflicts_with` | 자유 텍스트 | 충돌 감지 (P1.2: 양방향 무결성 검증) |
| `superseded_by` | 자유 텍스트 ([[wikilink]] 권장) | P3.1: stale decision의 자동 replacement_pointer |
| `decision_candidates` | 배열 (note 전용) | candidate 버킷 분류 |
| `tags` | 배열 | 임베딩에 포함, 표시 |
| `mocs` | 배열 | 표시 (MCP는 미사용) |
| `sources` | 배열 | 표시 (MCP는 미사용) |
| `context` | 자유 텍스트 | 본문에 포함되어 임베딩 |

## 필드별 상세

### `type` (필수)

문서의 정체성. 검색 부스팅과 버킷 분류의 1차 키.

| 값 | 의미 | 권한 영향 |
|---|---|---|
| `decision` | 결정 문서 | 부스팅 +0.15. fresh일 때 `decided_applicable` 후보 |
| `note` | 일반 노트 | 부스팅 0. `decision_candidates` 있으면 `candidate` |
| `moc` | Map of Content | 부스팅 0, path_role −0.02 |
| `source` | 외부 자료 | 부스팅 0, path_role −0.03 |
| `daily` | 데일리 노트 | 특별 처리 없음 |

→ **권한을 가지려면 반드시 `type: decision`**.

### `status`

문서의 현재 상태. 부스팅 + stale 판정 양쪽에 영향.

| 값 | 부스팅 | decision의 stale 여부 |
|---|---|---|
| `decided` | +0.05 | 통과 (fresh 후보) |
| `confirmed` | +0.05 | stale (decision은 decided만 살아있음) |
| `draft` | −0.05 | stale |
| `hypothesis` | 0 | stale |
| `archived` | 0 | stale |
| `active`, `raw` | 0 | stale |

→ Decision은 **`decided`만 살아있는 결정**. note는 `confirmed`까지 가산점.

### `decision_status` (decision 전용)

결정의 **사망 선고** 필드. 비어있으면 살아있고, 값이 있으면 즉시 stale.

| 값 | 의미 |
|---|---|
| (빈 문자열) | 정상 |
| `superseded` | 다른 결정으로 대체됨 |
| `deprecated` | 폐기 예정 |
| `retired` | 은퇴 |

→ 결정을 죽일 때 본문 지우지 말고 이 한 줄만 추가. 검색엔 잡히지만 권한은 박탈된다.

**P3.2 변경**: 이 필드는 이제 `_is_historical_negative` 판정의 **1차 매칭 키**이기도 함. archive 폴더 + 본문 키워드(`폐기`/`대체`/...) 매칭 방식은 보조로 강등. frontmatter에 명시적으로 `decision_status` 적힌 결정은 본문에 거부 키워드 없어도 `historical_negative` 신호 발동.

### `superseded_by` (P3.1 신설, decision 전용)

결정이 다른 결정으로 대체됐을 때 새 결정을 가리키는 frontmatter 필드.

```yaml
---
type: decision
decision_status: superseded
superseded_by: "[[Decision - 새 결정 제목]]"
---
```

**효과**: `advise()` 응답에서 이 옛 결정이 stale로 잡힐 때 `basis[0].replacement_pointer` 또는 `next_steps`에 *"See [[Decision - 새 결정]]"* 자동 첨부 → Claude가 한 번에 새 결정으로 안내.

본문 `## Superseded by [[X]]` 섹션과 동시 존재 시 frontmatter 우선. 본문은 사람용 reference로 보존.

### `revisit_when`

결정의 **자가 만료 트리거** 또는 재검토 메모.

`advisor.py`의 정규식:
```python
DATE_PATTERN = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
```

자동 만료 작동 조건 (3개 모두 충족):
1. 텍스트 어딘가에 `20XX-XX-XX` 패턴 매칭
2. `date.fromisoformat()`이 파싱 가능
3. 추출 날짜 ≤ 오늘

자유 텍스트만 있으면 자동 만료 안 됨, 메모로만 작동.

작성 패턴:
```yaml
# ✅ 자동 만료 작동
revisit_when: "2026-08-01"
revisit_when: "vault 300노트 도달 시 또는 2026-12-31"

# ❌ 자동 만료 작동 안 함 (메모로만)
revisit_when: "MCP 운영 2-4주 후"
revisit_when: "2026/08/01"        # 슬래시 안 됨
revisit_when: "2026-8-1"          # 0 패딩 필요
```

### `decided_on` / `created` / `updated`

날짜 메타. `decision_timeline` 도구가 `decided_on`으로 정렬. 나머지는 표시용.

### `conflicts_with`

명시적 **충돌 선언**. 다른 fresh decision의 title 또는 relative_path가 이 텍스트에 부분 매칭되면 → `decided_conflicting` → 사용자에게 escalate.

```yaml
conflicts_with: "Decision - Payment MSA 비동기 경로 Kafka 채택"
```

> 구현 노트: `indexer.py:prepare_document`가 이 필드를 ChromaDB 메타데이터에 저장하고, `advisor.py:_has_conflict`가 검색 결과 간 부분 문자열 매칭으로 충돌을 감지한다. 양쪽 결정에 모두 명시하는 것이 권장된다 (한쪽만 적으면 그쪽 결정이 검색에 잡힐 때만 conflict가 잡힘).

### `decision_candidates` (note 전용)

아직 결정 안 난 후보 옵션 배열. note에 사용.

```yaml
type: note
decision_candidates:
  - "Option A: Hazelcast 락 유지"
  - "Option B: 락 제거 후 idempotency key"
```

→ active_note + 비어있지 않으면 → `candidate` 버킷 → `ask_confirmation` 권고.

### `tags`

주제 태그 배열. 검색 텍스트에 포함되어 임베딩 품질에 기여.

### `mocs`, `sources`

연결 메타. MCP는 저장만 하고 검색·판정에 직접 사용 안 함. Obsidian 그래프 탐색용.

### `context`

문서가 왜 만들어졌는지 한 단락.

**⚠️ 중요**: frontmatter의 `context` 값 자체는 **임베딩에 포함되지 않는다**. `prepare_document`(`indexer.py:116-120`)는 search_text를 `# title\ntype | status | tags\n\nbody`로만 구성한다. frontmatter 영역은 search_text에 안 들어간다.

→ 핵심 맥락은 반드시 본문 `## Context` 섹션에 적어야 검색에 잡힌다. frontmatter `context`만 적고 본문에 안 적으면 검색 품질이 크게 떨어진다.

## 시스템 자동 부착 메타 (frontmatter 아님)

| 필드 | 출처 |
|---|---|
| `path_role` | 폴더 + type 추론 |
| `has_decision_candidates` | `decision_candidates` 비어있지 않으면 true |
| `content_hash` | body의 SHA-256 |
| `mtime` | 파일 수정 시각 — 증분 인덱싱 키 |
| `relative_path`, `file_path` | 경로 메타 |
| `title` | 파일명 stem |

## 타입별 템플릿

### Decision

```yaml
---
type: decision
status: decided
decided_on: 2026-04-16
revisit_when: 2026-08-01      # 절대 날짜 권장
decision_status: ""
conflicts_with: ""
tags: [decision, payment, msa]
mocs: ["[[MOC - Engineering]]"]
sources: ["self"]
context: "이 결정이 왜 필요했는지"
---
```

### Note (후보 정리)

```yaml
---
type: note
status: confirmed
decision_candidates:
  - "Option A: ..."
  - "Option B: ..."
tags: [analysis, payment]
mocs: ["[[MOC - Engineering]]"]
---
```

### MOC

```yaml
---
type: moc
status: active
tags: [moc, engineering]
---
```

### Source

```yaml
---
type: source
status: raw
tags: [source, paper]
sources: ["https://..."]
---
```

## fresh & applicable의 정의

```
fresh & applicable Decision
  ⇔ type == "decision"
  ∧ status == "decided"
  ∧ decision_status ∉ {superseded, deprecated, retired}
  ∧ revisit_when의 날짜가 미래 (또는 날짜 없음)
  ∧ conflicts_with가 다른 fresh decision과 매칭되지 않음
  ∧ similarity ≥ 0.35
```

이 5개 중 하나라도 무너지면 권한이 떨어진다. 가장 흔한 케이스는 `revisit_when` 날짜 도래로 자동 stale, 그다음이 `decision_status: superseded`로 명시적 폐기.

## 권한 영향 매트릭스

| 필드 | 검색 부스팅 | stale 판정 | 충돌 감지 | 버킷 분류 | 임베딩 |
|---|---|---|---|---|---|
| `type` | ✅ +0.15 | — | — | ✅ 1차 키 | — |
| `status` | ✅ ±0.05 | ✅ ≠decided→stale | — | — | — |
| `decision_status` | — | ✅ sup/dep/ret→stale | — | — | — |
| `revisit_when` | — | ✅ 날짜 ≤ today | — | — | — |
| `conflicts_with` | — | — | ✅ | — | — |
| `decision_candidates` | — | — | — | ✅ candidate | — |
| `tags`, `context` | — | — | — | — | ✅ |
| `mocs`, `sources` | — | — | — | — | — (표시만) |
