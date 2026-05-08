# vault-decision-mcp 문서

이 폴더는 vault-decision-mcp의 동작·설계·운영 분석을 정리한 문서 모음이다.

## 문서 목록

### 개념·아키텍처

| 문서 | 다루는 내용 |
|---|---|
| [01-architecture.md](./01-architecture.md) | 전체 아키텍처, 데이터 흐름, 기술 스택, 설계 철학 |
| [02-vault-structure.md](./02-vault-structure.md) | vault 폴더 구조와 path_role, frontmatter 컨벤션 |
| [03-frontmatter-fields.md](./03-frontmatter-fields.md) | frontmatter 필드별 용도, 타입 값별 의미, 권한 영향 |

### 동작·라이프사이클

| 문서 | 다루는 내용 |
|---|---|
| [04-indexing-and-sync.md](./04-indexing-and-sync.md) | watchdog → indexer → ChromaDB 동기화 체인, mtime 증분 인덱싱, 안전장치 |
| [05-search-and-advise.md](./05-search-and-advise.md) | query/advise 호출 한 번이 거치는 16단계 흐름 |
| [06-decision-lifecycle.md](./06-decision-lifecycle.md) | Decision의 일생, 자동 만료 기준, 사람의 개입 시점과 방법 |
| [07-troubleshooting.md](./07-troubleshooting.md) | 자주 발생하는 문제, 복구 절차, 운영 관찰, 테스트 실행, 알려진 한계 |
| [08-trigger-paths.md](./08-trigger-paths.md) | vault MCP 호출 경로 3가지(자동 훅·명시·자발), 트리거 패턴, 테스트 프롬프트 |

### 시각화

| 파일 | 용도 |
|---|---|
| [vault-decision-mcp-architecture.excalidraw](./vault-decision-mcp-architecture.excalidraw) | 전체 흐름 + 권한 레벨 → 행동 매핑 |
| [frontmatter-lifecycle.excalidraw](./frontmatter-lifecycle.excalidraw) | 필드 상관관계 + Decision 생명주기 + 트리거/주기 |

## 빠른 시작

처음 보는 사람은 다음 순서로 읽으면 된다:

1. **`01-architecture.md`** — 이 시스템이 뭐고 왜 만들었는지
2. **`02-vault-structure.md`** — vault가 어떻게 구성되어야 하는지
3. **`05-search-and-advise.md`** — 실제 호출이 어떻게 처리되는지
4. **`06-decision-lifecycle.md`** — 결정을 어떻게 운영해야 하는지

depth가 필요하면 `03`(필드별), `04`(동기화)를 본다. 운영 중 문제가 생기면 `07`을 본다.

## 한 줄 요약

vault는 frontmatter로 자기 권한 수명을 선언하는 ADR 레지스트리, MCP 서버는 그 vault를 LLM의 1차 의사결정자로 위임하는 게이트.
