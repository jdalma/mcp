# MCP Servers

개인용 MCP(Model Context Protocol) 서버 모음.

## vault-decision-mcp

Obsidian vault의 Decision/Note 파일을 로컬 embedding으로 인덱싱하고, Claude Code에서 semantic 검색할 수 있는 MCP 서버.

### 주요 기능

- **Semantic 검색** — 한국어+영어 혼합 vault를 `KR-SBERT` 모델로 임베딩, ChromaDB에서 유사도 검색
- **Decision 부스팅** — `type: decision` 문서에 가중치를 부여하여 의사결정 기록 우선 노출
- **증분 인덱싱** — mtime 기반으로 변경된 파일만 업데이트 (전체 리빌드 옵션 지원)
- **자동 리인덱싱** — watchdog으로 vault 파일 변경 감지 시 자동 증분 인덱싱
- **단일 상주 프로세스** — 모든 Claude Code 세션이 하나의 HTTP 서버를 공유 (임베딩 모델 1회 로드)

### MCP Tools

| Tool | 설명 |
|------|------|
| `query` | vault semantic 검색 |
| `list_decisions` | Decision 파일 목록 |
| `read_decision` | 특정 파일 전문 읽기 |
| `reindex` | 수동 리인덱싱 (force 옵션) |
| `stats` | 인덱스 상태 (타입/상태 분포) |
| `decision_timeline` | 시간순 Decision 이력 |

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
