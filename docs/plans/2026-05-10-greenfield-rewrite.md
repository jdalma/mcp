---
title: "vault-decision-mcp v2 — Greenfield Rewrite Plan"
date: 2026-05-10
status: draft
human_reviewed: false
related:
  - .omc/wiki/lesson-personal-tool-principles.md
  - .omc/wiki/method-dead-weight.md
  - https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
  - https://jsonobject.com/building-your-own-llm-wiki-with-claude-code-a-minimalist-s-guide-without-the-obsidian-lock-in
---

# vault-decision-mcp v2 — Greenfield Rewrite Plan

## 0. 한 줄 요약

기존 1527 LOC, 8 MCP tool, ChromaDB + watcher + 자체 호출 로거의 v1을 폐기하고, **FTS5 + bge-m3 임베딩 RRF 융합**을 핵심으로 한 ~730 LOC, 5 MCP tool의 v2로 재작성한다.

## 1. 배경

### 1.1 v1의 진단

`.omc/wiki/lesson-personal-tool-principles.md` 및 `method-dead-weight.md`에서 자가 진단한 결과:

- v1은 5개 설계 원칙(production이 없으면 production-grade 거부 / dead weight 30% 임계 / 외부 리뷰 컨텍스트 보정 / 분석 문서 비대 경계 / 핵심 2가지만 보장)을 모두 위반.
- B1~B8 정리(swap 제거, 회귀 baseline 제거, lint 4룰 축소 등) 후에도 dead weight ~25~35% 잔존.
- 인지 부하가 높아 6개월 후 자가 이해가 어려운 상태.

### 1.2 두 레퍼런스의 합류점

- **Karpathy LLM Wiki gist**: wiki는 "compiled artifact". 인간은 출처 선별, LLM은 bookkeeping. 자동 ingest watcher 거부. 스키마는 도메인이 정의.
- **JSONobject LLM Wiki guide**: "Borrow the convention, drop the app" — Obsidian frontmatter/wikilinks 형식만 빌리고 앱 종속 거부. `human_reviewed: true/false` 게이트 도입. SQLite FTS5 BM25 + ripgrep + `mq` 트리플로 벡터DB 거부.

본 프로젝트는 두 레퍼런스의 정신을 받되, 검색 품질이 의사결정 품질을 좌우한다는 사용자 판단에 따라 임베딩을 *옵션이 아닌 1차 시민*으로 유지한다. 단, ChromaDB 같은 인프라 부산물은 거부한다.

## 2. 핵심 가치 (non-negotiable)

> Claude Code가 다른 프로젝트에서 의사결정이 필요할 때, 내 vault에 이미 내려진 결정을 검색·판정해서 권위 있는 결정에 따르도록 권한 신호를 준다.

이 한 문장에서 도출되는 4가지:

1. **검색**: 자연어 질문 → vault에서 관련 Decision/Note 찾기.
2. **권위 판정**: 따라야 하는 결정 / 참고만 가능한 노트 / 폐기·보류된 신호로 분류.
3. **추천 액션**: `proceed` / `ask_confirmation` / `do_not_proceed` / `answer_with_citation` / `ask_user`.
4. **무결성**: 양방향 `conflicts_with`, `revisit_when` 만료, `superseded` 미선언 같은 bookkeeping.

## 3. 요구사항

### 3.1 기능 요구사항

| ID  | 요구사항                                                                                                                                | 우선순위 |
| --- | --------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| FR-1 | 자연어 질문으로 vault에서 관련 Decision/Note 검색                                                                                       | P0       |
| FR-2 | 권위 수준 분류: `decided_applicable` / `decided_stale` / `decided_conflicting` / `candidate` / `note_only` / `historical_negative` / `none` | P0       |
| FR-3 | 추천 액션 산출                                                                                                                         | P0       |
| FR-4 | 모든 인용은 `vault상대경로[:헤딩]` 형식                                                                                                  | P0       |
| FR-5 | `human_reviewed: false` 또는 `00 Inbox/` 노트는 권위 근거에서 제외                                                                       | P0       |
| FR-6 | 양방향 `conflicts_with` 위반 감지                                                                                                       | P1       |
| FR-7 | `revisit_when` 만료 결정 감지                                                                                                           | P1       |
| FR-8 | `## Superseded by` 본문 있으나 frontmatter `decision_status` 비어있는 경우 감지                                                          | P2       |

### 3.2 비기능 요구사항

| ID    | 요구사항                                                                            |
| ----- | ----------------------------------------------------------------------------------- |
| NFR-1 | 단일 사용자, 단일 프로세스, 로컬 stdio MCP. macOS launchctl 상시 대기.              |
| NFR-2 | 외부 노출 없음. 보안 boundary, path-escape 가드 없음.                               |
| NFR-3 | swap·atomic·lock·redaction·model mismatch 검증 없음. reindex는 통째 재빌드 한 가지. |
| NFR-4 | watcher 없음. reindex는 명시적 tool 호출로만.                                       |
| NFR-5 | 호출 로그는 stderr `logger`만. JSONL 별도 로거 없음.                                |
| NFR-6 | 코드 총량 ≤ 700 LOC 목표.                                                           |
| NFR-7 | MCP tool 5개로 한정.                                                                |
| NFR-8 | 검색 결과는 BM25/임베딩/RRF 점수 분해를 디버그 출력 가능.                           |

### 3.3 명시적 거부 항목

- ❌ Watchdog auto-reindex
- ❌ ChromaDB
- ❌ JSONL call_logger
- ❌ atomic swap, lock, redaction, model mismatch 검증
- ❌ path-escape 가드 (`_resolve_allowed_markdown`)
- ❌ question classifier 4분류 (destructive vs non-destructive 2분류로 축소)
- ❌ TYPE/STATUS/PATH_ROLE 3중 boost (FTS5 컬럼 가중치 + RRF가 대체)
- ❌ `stats`, `decision_timeline`, `list_decisions` MCP tool
- ❌ 회귀 baseline 픽스처, adversarial 픽스처

## 4. 기술 스택

| 레이어            | 채택                                            | 비고                                          |
| ----------------- | ----------------------------------------------- | --------------------------------------------- |
| 언어              | Python 3.11+                                    | `uv` 빌드                                     |
| MCP SDK           | `mcp.server.fastmcp` (stdio transport)          | streamable-http 미사용                        |
| Frontmatter       | `pyyaml`                                        | —                                             |
| 검색 1차 (lexical) | SQLite FTS5 + `unicode61` + 컬럼 가중치         | Python 표준 `sqlite3`                         |
| 검색 2차 (semantic)| BAAI/bge-m3 (dense, 1024차원)                   | `sentence-transformers`                        |
| 융합              | RRF (k=60), 양쪽 top-30 → 합산 → top-15         | rank-only 합산, 점수 직접 비교 안 함           |
| 임베딩 저장       | SQLite BLOB 컬럼 (FTS5와 같은 DB 파일)          | numpy 코사인 유사도 brute-force                |
| 인덱스 위치       | `~/.cache/vault-decision-mcp/index.db`          | 단일 파일                                     |
| 로그              | stderr `logger.info`                            | —                                             |

**의존성 합계**: `mcp`, `pyyaml`, `sentence-transformers` (`torch` 자동 동반), `numpy`.

## 5. MCP Tool 카탈로그 (5개 확정)

| Tool             | 입력                              | 출력                                                              | 설명                                          |
| ---------------- | --------------------------------- | ----------------------------------------------------------------- | --------------------------------------------- |
| `advise`         | `question: str, max_results=5`    | `{authority_level, recommended_action, basis[], warnings[], next_steps[]}` | 검색 + 권위 판정 + 액션 산출                  |
| `query`          | `question: str, max_results=5`    | 마크다운 텍스트 (인용 포함)                                       | 검색만, 권위 판정 없이 raw                    |
| `read_decision`  | `file_name: str`                  | 마크다운 본문 또는 `"File not found: {path}"`                     | path-escape 가드 없음 (NFR-2). 파일 없음 시 문자열 반환, 예외 raise 안 함 |
| `lint`           | —                                 | `{issues[], summary}`                                             | 3룰: asymmetric_conflict / stale_decision / superseded_dangling |
| `reindex`        | —                                 | `"Indexed N documents"`                                           | 통째 재빌드, force/incremental 구분 없음      |

## 6. Vault 컨벤션

### 6.1 디렉터리 (현 vault 구조 그대로)

```
~/knowledge/memory-palace/
├── 00 Inbox/             # 미검토. 권위 근거 X
├── 01 Notes/
│   ├── Decision - *.md   # type=decision
│   └── *.md              # type=note
├── 02 Maps/              # MOC, navigation only
├── 03 Sources/           # 외부 자료
├── 99 Archive/           # 폐기/superseded
└── index.md              # decisions 섹션 = source-of-truth 목록
```

### 6.2 Frontmatter 최소 스키마

```yaml
---
type: decision | note
status: decided | draft | superseded
human_reviewed: true | false      # 신규 도입. 필수.
decided_on: YYYY-MM-DD            # decision일 때 권장
revisit_when: YYYY-MM-DD          # 선택
decision_status: active | superseded | deprecated   # decision일 때
superseded_by: "Decision - ..."   # 선택
conflicts_with: ["Decision - ..."]
context: "한 줄 요약"             # 검색 품질 향상용
---
```

### 6.3 권위 판정 룰

```
path startswith "00 Inbox/"            → 무조건 제외
human_reviewed != true                  → note_only로 강등
type=decision AND status=decided AND
  decision_status != superseded AND
  (revisit_when 없음 OR 미래)            → decided_applicable
type=decision AND 위 조건 실패          → decided_stale
fresh decisions 중 conflicts_with 위반  → decided_conflicting
type=note AND human_reviewed=true      → note_only
path startswith "99 Archive/"          → historical_negative
```

## 7. SQLite 스키마

```sql
-- 1) 메타 + 임베딩
CREATE TABLE docs (
  rowid          INTEGER PRIMARY KEY,
  path           TEXT UNIQUE NOT NULL,
  title          TEXT NOT NULL,
  type           TEXT,
  status         TEXT,
  decision_status TEXT,
  human_reviewed INTEGER,        -- 0/1
  decided_on     TEXT,
  revisit_when   TEXT,
  superseded_by  TEXT,
  conflicts_with TEXT,           -- JSON array as TEXT
  context        TEXT,
  body           TEXT NOT NULL,
  mtime          REAL NOT NULL,
  embedding      BLOB            -- bge-m3 1024-dim float32
);

CREATE INDEX idx_docs_path ON docs(path);

-- 2) FTS5 (외부 컨텐츠 모드)
CREATE VIRTUAL TABLE docs_fts USING fts5(
  title, context, body,
  content='docs',
  content_rowid='rowid',
  tokenize="unicode61 remove_diacritics 2"
);

-- 3) 트리거: docs ↔ docs_fts 동기화
CREATE TRIGGER docs_ai AFTER INSERT ON docs BEGIN
  INSERT INTO docs_fts(rowid, title, context, body)
  VALUES (new.rowid, new.title, new.context, new.body);
END;

CREATE TRIGGER docs_ad AFTER DELETE ON docs BEGIN
  INSERT INTO docs_fts(docs_fts, rowid, title, context, body)
  VALUES ('delete', old.rowid, old.title, old.context, old.body);
END;

CREATE TRIGGER docs_au AFTER UPDATE ON docs BEGIN
  INSERT INTO docs_fts(docs_fts, rowid, title, context, body)
  VALUES ('delete', old.rowid, old.title, old.context, old.body);
  INSERT INTO docs_fts(rowid, title, context, body)
  VALUES (new.rowid, new.title, new.context, new.body);
END;
```

검색 쿼리 예:
```sql
SELECT path, bm25(docs_fts, 5.0, 3.0, 1.0) AS score
FROM docs_fts
WHERE docs_fts MATCH ?
ORDER BY score
LIMIT 30;
```

**malformed frontmatter 처리**: YAML 파싱 실패 시 `meta = {}`로 fallback + stderr warning 1줄. 본문(body)은 정상 인덱싱하여 검색에서 누락되지 않게 한다.

## 8. 검색 파이프라인

`advise` / `query` 공통:

```
1. FTS5 BM25: 제목 5x, context 3x, body 1x → top-30
2. 질문 임베딩 (bge-m3 dense) + docs.embedding 코사인 → top-30
3. RRF 합산: score(d) = Σ 1/(60 + rank_i(d))
4. RRF top-15를 권위 판정 입력으로 전달
5. _decision_entries / _note_entries / _historical_negative 분류
6. authority_level + recommended_action 산출
```

**FTS5 MATCH 입력 sanitization**: 자연어 질문은 FTS5 special token(`AND`, `OR`, `NOT`, `NEAR`, `"`, `*`, `:`, `-`, `(`, `)`)을 포함할 수 있으므로 다음 규칙으로 정제 후 MATCH에 전달한다.

1. special character는 공백으로 치환.
2. 토큰화 후 빈 토큰 제거.
3. 각 토큰을 double-quote로 감싸고 공백으로 join (FTS5 phrase syntax 회피, 모든 토큰을 prefix-free literal로 취급).
4. 최종 결과가 빈 문자열이면 검색 skip하고 임베딩 결과만 사용.

예: `Redis 캐시 만료 정책?` → `"Redis" "캐시" "만료" "정책"`

## 9. 디렉터리 구조 (그린필드)

```
vault-decision-mcp/
├── pyproject.toml
├── start-server.sh
├── com.vault-decision-mcp.plist
├── README.md
├── docs/
│   └── plans/2026-05-10-greenfield-rewrite.md
└── vault_decision/
    ├── __init__.py
    ├── server.py          # FastMCP + 5 tools          (~150 LOC)
    ├── config.py          # env 읽기                    (~30)
    ├── indexer.py         # SQLite + FTS5 + 임베딩      (~200)
    ├── searcher.py        # BM25 + 임베딩 + RRF         (~120)
    ├── advisor.py         # 권위 판정 + 추천 액션       (~150)
    └── lint.py            # 3룰                         (~120)
```

총 ~770 LOC 추정. NFR-6의 700 LOC 목표를 살짝 초과 — 작성 후 simplify pass로 ≤ 700 목표.

## 10. 마이그레이션 절차

1. 기존 `vault-decision-mcp/` 패키지를 `vault-decision-mcp/_archive_v1/`로 이동(완전 삭제 X, 회귀 시 참조용으로 1주만 보관).
2. 새 `vault_decision/` 패키지 작성. `pyproject.toml` 의존성 갱신.
3. **모델 사전 다운로드**: `python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3')"`. 첫 launchctl 기동 전에 수동 실행. 실패 시 `pip install torch sentence-transformers` 단계 검증 후 재시도. macOS arm64 wheel 가용성 확인 필수.
4. `~/.cache/vault-decision-mcp/index.db` 신규 생성. 기존 `.chroma/` 삭제 가능.
5. 기존 vault 파일에 `human_reviewed` 필드 일괄 마이그레이션 (별도 스크립트 1회).
6. `~/.claude.json` 또는 `mcp.json`에서 서버 명령 갱신.
7. **launchctl plist 환경변수**: plist의 `EnvironmentVariables` dict에 다음 키 명시(launchd context는 shell env를 상속하지 않음).
   ```xml
   <key>EnvironmentVariables</key>
   <dict>
     <key>VAULT_PATH</key><string>/Users/jeonghyunjun/knowledge/memory-palace</string>
     <key>HF_HOME</key><string>/Users/jeonghyunjun/.cache/huggingface</string>
     <key>VAULT_DECISION_INDEX</key><string>/Users/jeonghyunjun/.cache/vault-decision-mcp/index.db</string>
   </dict>
   ```
   reload: `launchctl unload ~/Library/LaunchAgents/com.vault-decision-mcp.plist && launchctl load ~/Library/LaunchAgents/com.vault-decision-mcp.plist`.
8. 1주 운영, 회귀 없으면 `_archive_v1/` 삭제.

## 11. Phase 분해

### Phase 0 — 청소 + 골격 (0.5일)
- v1 패키지를 `_archive_v1/`로 이동
- 새 `vault_decision/` 디렉터리 + `__init__.py` + `pyproject.toml` 갱신
- `start-server.sh`, plist 임시 동작 확인

### Phase 1 — 코어 검색 (1일)
- `config.py` (env 읽기, 인덱스 경로)
- `indexer.py`: 파일 수집 → frontmatter 파싱 → SQLite docs 삽입 → 임베딩 → FTS5 트리거
- `searcher.py`: BM25 쿼리 + 임베딩 코사인 + RRF 합산
- 단위 동작: `python -m vault_decision.indexer build && python -m vault_decision.searcher "캐시 전략"` 같은 CLI 보조 스크립트로 즉시 검증

### Phase 2 — 권위 판정 + MCP 노출 (0.5일)
- `advisor.py`: 권위 룰 + 추천 액션
- `server.py`: 5 tool 등록, lifespan에서 `_ensure_indexed()` 1회 호출
- MCP inspector로 5 tool 호출 확인

### Phase 3 — Lint 3룰 (0.5일)
- `lint.py`: asymmetric_conflict / stale_decision / superseded_dangling
- vault 실제 파일에서 false positive 0 확인

### Phase 4 — Vault 마이그레이션 + 운영 전환 (0.5일)
- `human_reviewed` 일괄 추가 스크립트(별도 1회용, 본 패키지에 안 둠)
- launchctl reload
- 1주 dogfooding

총 추정: **3일**.

## 12. 검증 기준 (Phase 별)

| Phase | 검증                                                                                        |
| ----- | ------------------------------------------------------------------------------------------- |
| 1     | 200~500노트 인덱스 빌드 < 30초. 쿼리 1회 < 300ms.                                            |
| 2     | 동일 질문 5개에 대해 v1과 v2의 top-3 결정 일치율 ≥ 80%.                                       |
| 3     | vault 현재 상태에서 lint() 호출 시 의미 있는 issue만 보고. false positive 0.                 |
| 4     | Claude Code 다른 프로젝트에서 1주간 advise() 호출 시 정답 결정 누락 0건.                     |

## 13. 위험 / 미리 답해둔 질문

- **Q. bge-m3 모델 다운로드가 첫 실행 시 네트워크 필요한데?**
  A. 첫 실행 1회만. launchctl 상시 대기 후엔 영향 없음. **§10 step 3에서 수동 사전 다운로드 강제** — launchd context에서 첫 다운로드가 실패하는 케이스 회피.
- **Q. torch 설치/임베딩 모델 로드 자체가 실패하면?**
  A. 본 프로젝트는 fallback 없음 (single point of failure 수용 — 미니멀리즘 원칙 1). 실패 시 서버는 stderr에 명확한 traceback을 남기고 종료. 사용자가 의존성 설치를 수동 복구. launchctl `StandardErrorPath`로 로그 캡처하여 진단.
- **Q. FTS5 MATCH에 사용자 질문을 넣을 때 syntax error가 날 수 있나?**
  A. §8의 sanitization 로직으로 special token 제거 + double-quote wrapping. 추가로 `sqlite3.OperationalError` catch 후 빈 결과 반환하고 임베딩 결과만 사용.
- **Q. launchctl이 shell env를 상속하지 않아 VAULT_PATH가 비어 있으면?**
  A. plist의 `EnvironmentVariables`에 명시 (§10 step 7). config.py는 `VAULT_PATH` 미설정 시 즉시 RuntimeError로 실패하도록 한다 (silent default 거부).
- **Q. SQLite FTS5의 한국어 토큰화는?**
  A. `unicode61`은 띄어쓰기 단위. 부족하면 trigram 토크나이저 옵션 추가. 단, 임베딩 RRF가 의미 매칭을 잡으므로 우선 `unicode61`로 시작.
- **Q. 임베딩 차원(1024)을 SQLite BLOB에 저장할 때 크기는?**
  A. float32 × 1024 = 4KB/문서. 500노트면 2MB. 무시 가능.
- **Q. brute-force 코사인 유사도가 500노트에서 충분한가?**
  A. numpy dot product로 < 5ms. 충분.
- **Q. v1 archive를 정말 1주 후 삭제?**
  A. 1주 dogfooding에서 회귀 없으면 삭제. 회귀 있으면 v1 복구 → v2 재진단.

## 14. 합의 사항 (이 plan을 시작으로 못박음)

- 검색 엔진: **D' (FTS5 + bge-m3 dense + RRF)**
- 마이그레이션: **그린필드**
- MCP tool: **5개 (advise/query/read_decision/lint/reindex)**
- Frontmatter: **`human_reviewed` 도입**
- LLM 프롬프트 확장: **사용 안 함**
- 서버 수명: **launchctl 상시 대기**

## 15. 다음 단계

이 plan 검토 완료 후 Phase 0부터 순차 진행. 각 Phase 종료 시 사용자 확인 게이트 1회.
