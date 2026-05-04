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
