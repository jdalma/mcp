# MCP Servers

개인용 MCP(Model Context Protocol) 서버 모음.

## vault-decision-mcp

Obsidian vault의 Decision/Note 파일을 로컬 embedding으로 인덱싱하고, Claude Code에서 semantic 검색할 수 있는 MCP 서버.

### 주요 기능

- **Semantic 검색** — 한국어+영어 혼합 vault를 `KR-SBERT` 모델로 임베딩, ChromaDB에서 유사도 검색
- **Decision 부스팅** — `type: decision` 문서에 가중치를 부여하여 의사결정 기록 우선 노출
- **권한 판정** — `advise`가 Decision/Note/후보/Archive 근거를 구분해 agent 행동 권고 반환
- **증분 인덱싱** — mtime 기반으로 변경된 파일만 업데이트 (전체 리빌드 옵션 지원)
- **자동 리인덱싱** — watchdog으로 vault 파일 변경 감지 시 자동 증분 인덱싱
- **단일 상주 프로세스** — 모든 Claude Code 세션이 하나의 HTTP 서버를 공유 (임베딩 모델 1회 로드)

### MCP Tools

| Tool | 설명 |
|------|------|
| `query` | vault semantic 검색 |
| `advise` | 검색 결과를 `authority_level`, `question_type`, `recommended_action`으로 판정 |
| `list_decisions` | Decision 파일 목록 |
| `read_decision` | 특정 파일 전문 읽기 |
| `reindex` | 수동 리인덱싱 (force 옵션) |
| `stats` | 인덱스 상태 (타입/상태 분포) |
| `decision_timeline` | 시간순 Decision 이력 |

### Authority levels

`advise`는 아래 권한 수준 중 하나를 반환한다.

| Level | 의미 |
|-------|------|
| `decided_applicable` | 관련 active Decision이 있고 stale/conflict 신호가 없음 |
| `decided_stale` | 관련 Decision이 있으나 재검토/대체 가능성이 있음 |
| `decided_conflicting` | 관련 Decision 간 충돌 신호가 있음 |
| `note_only` | 일반 Note 근거만 있음 |
| `candidate` | `decision_candidates`만 있음 |
| `historical_negative` | Archive에 폐기/거부/대체 이력 신호가 있음 |
| `none` | 사용 가능한 vault 근거가 없음 |

### Tech Stack

- Python 3.13 + [uv](https://docs.astral.sh/uv/)
- [FastMCP](https://github.com/jlowin/fastmcp) (MCP 서버 프레임워크)
- [ChromaDB](https://www.trychroma.com/) (로컬 벡터 DB)
- [sentence-transformers](https://www.sbert.net/) (`snunlp/KR-SBERT-V40K-klueNLI-augSTS`)

### 설치 및 실행

```bash
cd vault-decision-mcp
uv sync
```

#### 서버 시작

```bash
# 직접 실행
./start-server.sh

# 포트 변경 시
MCP_PORT=9000 ./start-server.sh
```

#### macOS 로그인 시 자동 시작 (launchd)

```bash
# 등록
cp com.vault-decision-mcp.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.vault-decision-mcp.plist

# 해제
launchctl unload ~/Library/LaunchAgents/com.vault-decision-mcp.plist
```

로그 확인: `tail -f /tmp/vault-decision-mcp.log`

#### Claude Code 등록 (`~/.claude.json`)

서버를 먼저 실행한 뒤 아래 설정을 추가한다:

```json
{
  "mcpServers": {
    "vault-decision": {
      "type": "http",
      "url": "http://127.0.0.1:8765/mcp"
    }
  }
}
```

### 설정

| 환경변수 | 기본값 | 설명 |
|----------|--------|------|
| `VAULT_PATH` | `~/knowledge/memory-palace` | Obsidian vault 경로 |
| `VAULT_EMBEDDING_MODEL` | `snunlp/KR-SBERT-V40K-klueNLI-augSTS` | embedding 모델 |
| `MCP_HOST` | `127.0.0.1` | 서버 바인딩 주소 |
| `MCP_PORT` | `8765` | 서버 포트 |

### Claude Code 훅 연동 — Vault Decision Gate

사용자 질문이 "의사결정" 성격이면 응답 전에 자동으로 vault를 조회하도록 강제하는 `UserPromptSubmit` 훅 패턴이다. 정확도가 핵심이라 키워드 매칭을 보수적으로 잡아 두었다.

#### 파일 위치

| 경로 | 역할 |
|------|------|
| `~/.claude/hooks/shared/vault-decision-patterns.mjs` | 결정 질문 판별 정규식 (`DECISION_PATTERNS` / `NON_DECISION_PATTERNS`) |
| `~/.claude/hooks/user-prompt-submit/vault-decision-inject.mjs` | 매칭 시 `additionalContext`로 vault 조회 지시 주입 |

#### `~/.claude/settings.json` 등록

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          { "type": "command", "command": "node \"${CLAUDE_CONFIG_DIR:-$HOME/.claude}/hooks/user-prompt-submit/vault-decision-inject.mjs\"" }
        ]
      }
    ]
  }
}
```

#### 동작 조건

훅은 아래 셋이 모두 참일 때만 vault gate를 발동한다. 하나라도 빠지면 조용히 통과한다.

1. 사용자 메시지가 `DECISION_PATTERNS`에 매칭되고 `NON_DECISION_PATTERNS`에는 매칭되지 않음
2. `~/.claude.json`의 `mcpServers["vault-decision"].command`가 존재 (stdio MCP 설정)
3. `~/.cache/vault-decision-mcp/index.db` (또는 `$VAULT_DECISION_INDEX`)가 존재

#### 임시 비활성화

```bash
VAULT_DECISION_GATE=false claude  # 또는 0
```

#### 패턴 튜닝 가이드

`DECISION_PATTERNS`는 명사형 단일 키워드(`구현`, `설계`, `architecture`)만으로는 매칭하지 않는다. 단순 코드 작업 질문에서 false positive가 폭증하기 때문이다. 새 키워드를 추가할 때는 다음 중 하나의 형태를 따른다:

- 명시적 결정 동사: `decide`, `결정해야`, `선택할지`, `택할지`
- "선택지 + 의문형" 조합: `(approach|architecture|설계|방향) ... (어떻게|할까|좋을까|recommend)`
- 명시적 비교: `vs`, `versus`, `아니면`
- "X를 추천"류: `(library|framework|sdk) ... (recommend|추천|선택)`

수정 후에는 false positive/true positive 케이스를 둘 다 노드 스크립트로 회귀 검증한 뒤 반영한다.
