# 01. 아키텍처 개요

## 무엇을 해결하는 시스템인가

다른 프로젝트에서 Claude로 코딩 중일 때, 의사결정이 필요한 순간에 Claude가 사용자에게 직접 질문한다. 그런데 사용자의 vault(`~/knowledge/memory-palace`)에 이미 비슷한 결정·ADR·기술 노트가 쌓여 있는데 매번 사람이 답하는 건 낭비다.

**이 MCP 서버는 vault를 Claude의 "1차 의사결정자"로 위임한다.**

```
Claude가 "X로 갈까 Y로 갈까?" → vault 검색 → 답이 있으면 사용자에게 안 묻고 진행
                                       → 없으면/모호하면 사용자에게 escalate
```

## 전체 아키텍처

```
[Obsidian vault: 마크다운 + YAML frontmatter]
            │ watchdog (재귀 감시, 5초 디바운스)
            ▼
[indexer.py — mtime 비교 증분 인덱싱]
            │ KR-SBERT 임베딩
            ▼
[ChromaDB (.chroma/, persistent local)]
            │ semantic search + threshold 부스팅
            ▼
[searcher.py — TYPE × STATUS × PATH_ROLE 가중치]
            │
            ▼
[advisor.py — 결정론적 권한 룰]
            │  버킷 분리 → stale/conflict/negative 검사
            │  → authority_level → recommended_action
            ▼
[FastMCP @tool — advise / query / list_decisions / read_decision / reindex / stats / decision_timeline]
            │ HTTP/SSE (streamable-http)
            ▼
[Claude Code 다른 세션 — ~/.claude.json에 등록]
```

## 기술 스택

### 런타임
- **Python 3.13** + **uv** 패키지 관리
- **launchd plist**로 macOS 로그인 시 자동 시작 (`com.vault-decision-mcp.plist`)
- 단일 상주 프로세스 — 모든 Claude 세션이 하나의 HTTP 서버 공유 (임베딩 모델 1회 로드)

### 프로토콜
- **MCP (Model Context Protocol)** — Anthropic의 LLM-tool 통신 표준
- **FastMCP** (`mcp.server.fastmcp`) — `@mcp.tool()` 데코레이터
- **streamable-http** 트랜스포트, 127.0.0.1:8765 로컬 바인딩

### 검색·임베딩
- **ChromaDB** PersistentClient (sqlite 백엔드, `.chroma/`)
- **`snunlp/KR-SBERT-V40K-klueNLI-augSTS`** 임베딩 모델 (한국어 특화 SBERT)
- **sentence-transformers** 라이브러리로 HuggingFace 모델 로드
- 유사도: cosine distance → `1 - distance`로 변환

### 데이터·파싱
- Markdown + YAML frontmatter (Obsidian 컨벤션)
- **PyYAML** `yaml.safe_load`
- SHA-256으로 `content_hash` 생성

### 파일 감시
- **watchdog** — macOS는 PollingObserver(FSEvents 우회), Linux는 native inotify
- `threading.Timer`로 5초 디바운스
- `asyncio.run_coroutine_threadsafe`로 워처 스레드 → 메인 루프 다리

### 권한 판정
- 정규식 + dict 기반 결정론적 룰 (LLM 미사용)
- `datetime.date`로 `revisit_when` 만료 평가

### 관측성
- 표준 `logging` (stderr — stdout은 MCP 프로토콜 전용)
- `call_logger`로 도구 호출을 JSONL에 누적

## 핵심 설계 결정

### 1. 검색은 ML, 판정은 룰
ChromaDB+KR-SBERT는 의미 매칭만 담당하고 권한 판정(stale, conflict, authority_level)은 결정론적 룰로 분리. 디버깅·예측가능성 확보.

### 2. 단일 상주 프로세스
임베딩 모델은 무겁기 때문에(수 초 로드) launchd로 1회만 로드. 모든 Claude 세션이 같은 HTTP 엔드포인트 공유.

### 3. 로컬 우선
외부 API 0개, 모든 데이터/모델/인덱스가 디스크에 상주. 개인 vault 보안 + 오프라인 작동.

### 4. vault 컨벤션이 곧 인터페이스
`## Decision`/`## Rationale` 섹션, frontmatter 필드, 폴더 구조가 검색·판정 품질을 직접 결정. vault 작성 규칙이 사실상 API 스키마.

### 5. 부스팅 임계값
similarity ≥ 0.35인 후보에만 TYPE/STATUS/PATH_ROLE 부스팅 적용 → 무관한 결과의 부스팅 노이즈 차단.

### 6. 오버페치
사용자가 5개 달라고 해도 ChromaDB에서 최소 20개를 가져와 부스팅 후 컷 → 부스팅으로 순위가 바뀌는 경우를 살림.

## MCP 도구 목록

| 도구 | 용도 |
|---|---|
| `query` | semantic 검색, 사람이 읽기 좋은 markdown 반환 |
| `advise` | 검색 + 권한 판정. 구조화된 dict + summary 반환 |
| `list_decisions` | type=decision 문서 목록 |
| `read_decision` | 특정 vault 파일 전문 (경로 escape 차단) |
| `reindex` | 수동 인덱싱 (force 옵션으로 전체 리빌드) |
| `stats` | 문서 수, 타입/상태 분포 |
| `decision_timeline` | `decided_on` 기준 시간순 Decision 이력 |

## 환경변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `VAULT_PATH` | `~/knowledge/memory-palace` | Obsidian vault 경로 |
| `VAULT_EMBEDDING_MODEL` | `snunlp/KR-SBERT-V40K-klueNLI-augSTS` | embedding 모델 |
| `MCP_HOST` | `127.0.0.1` | 서버 바인딩 주소 |
| `MCP_PORT` | `8765` | 서버 포트 |
| `VAULT_WATCHER` | (자동) | `native`/`polling`로 강제 가능 |
