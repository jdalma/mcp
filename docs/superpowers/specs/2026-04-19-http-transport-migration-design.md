# vault-decision-mcp: stdio → streamable-http 전환 설계

- **작성일**: 2026-04-19
- **최종 수정**: 2026-04-20 (Codex 리뷰 반영)
- **상태**: 검토 완료

---

## 1. 배경

`vault-decision-mcp`는 Obsidian vault의 Decision 문서와 노트를 semantic 검색하여 Claude Code 세션에 과거 의사결정 컨텍스트를 제공하는 MCP 서버다.

현재 `FastMCP`의 `stdio` transport로 동작하며, Claude Code는 각 세션 시작 시 `uv run server.py` 명령으로 서버 프로세스를 직접 실행한다.

> **이전 이력**: `163090c`에서 daemon mode를 추가했다가 `286c400`에서 "Claude Code는 command-based MCP만 지원"이라는 이유로 제거했다. 이번 전환은 `streamable-http`를 Claude Code가 `type: http`로 지원한다는 점을 재확인한 뒤 진행한다. **Phase 0 spike에서 이를 먼저 검증한다.**

---

## 2. 현재 문제

### 2-1. 세션당 중복 초기화 (핵심 문제)

`server.py`의 `_ensure_initialized()`가 **각 세션의 첫 tool 호출 시** 다음을 실행한다:

```
SentenceTransformer 모델 로드 (~수백 MB)
  → chromadb.PersistentClient 연결
  → build_index() 전체 vault 스캔 및 upsert
  → start_watcher() 파일 감시 시작
```

Claude Code 세션이 4개 열려 있으면 이 과정이 **4번** 반복된다.

```
프로세스 목록 (실제 관찰):
  uv run server.py  ← s001 세션
  uv run server.py  ← s002 세션
  uv run server.py  ← s004 세션
  uv run server.py  ← s006 세션
```

### 2-2. 중복 watcher와 비조율 write

세션마다 독립된 watcher와 `_collection` 인스턴스가 실행된다. 정확히는:

- vault 파일이 변경될 때 watcher가 각 세션에서 **동시에** `build_index()`를 호출하여 동일 ChromaDB store에 중복 write가 발생한다
- 세션 A에서 `reindex`를 호출해도 세션 B, C, D의 인메모리 `_collection` 핸들이 갱신되는 보장이 없다 (ChromaDB `PersistentClient`가 디스크 변경을 자동으로 반영하지 않는 경우)

### 2-3. 첫 응답 지연

lazy init 구조상 첫 tool 호출 시 임베딩 모델 로드(수 초)가 응답 지연으로 나타난다.

---

## 3. 해결 방향

### 핵심 아이디어

서버를 **단일 상주 프로세스**로 전환하여 모든 Claude Code 세션이 하나의 인스턴스를 공유하도록 한다.

```
현재:
  [세션 A] → [server 프로세스 A] → ChromaDB
  [세션 B] → [server 프로세스 B] → ChromaDB
  [세션 C] → [server 프로세스 C] → ChromaDB

전환 후:
  [세션 A] ──┐
  [세션 B] ──┼── [server 프로세스 1개] → ChromaDB
  [세션 C] ──┘
```

### 선택한 방식: FastMCP streamable-http transport

`FastMCP`가 이미 `streamable-http` transport를 내장 지원한다. 코드 변경이 최소화된다.

```python
# 변경 전
mcp.run(transport="stdio")

# 변경 후
mcp.run(transport="streamable-http", host="127.0.0.1", port=8765)
```

Claude Code 설정:

```json
// ~/.claude.json (기존)
"vault-decision": {
  "command": "uv",
  "args": ["--directory", "...", "run", "server.py"]
}

// 전환 후
"vault-decision": {
  "type": "http",
  "url": "http://127.0.0.1:8765/mcp"
}
```

---

## 4. 전환으로 해결되는 문제

| 문제 | 현재 | 전환 후 |
|------|------|---------|
| 임베딩 모델 메모리 | 세션 수 × ~300MB | 1회 ~300MB |
| ChromaDB 연결 수 | 세션 수만큼 | 1개 |
| 중복 watcher | 세션 수만큼 실행 | 1개 |
| 비조율 중복 write | watcher가 동시에 upsert | 단일 프로세스 내 직렬화 |
| reindex 반영 범위 | 호출한 세션만 | 모든 세션 즉시 반영 |
| 첫 응답 지연 | 매 세션 초기화 비용 | 서버 시작 시 1회 |

---

## 5. 트레이드오프 및 리스크

### 장애 격리 약화

현재는 한 세션의 MCP 프로세스가 죽어도 다른 세션에 영향이 없다. 단일 프로세스 전환 후 서버가 죽으면 **모든 세션**이 영향을 받는다.

완화책: launchd 자동 재시작으로 다운타임을 최소화한다.

### 동시성 — search와 build_index의 충돌 (신규)

여러 세션이 동시에 `search()`를 호출하고, watcher 스레드가 동시에 `build_index()`를 실행할 수 있다. ChromaDB `PersistentClient`의 thread-safety가 보장되는지 확인이 필요하다.

완화책: `build_index()` 호출을 asyncio lock 또는 threading.Lock으로 직렬화한다. read(`search`) 와 write(`build_index`) 분리로 충분한지 검토한다.

### watcher 정상 종료 (신규)

서버 shutdown 시 watchdog `Observer`가 정상 종료되지 않으면 좀비 스레드가 남는다.

완화책: FastMCP lifespan 훅의 shutdown 단계에서 `observer.stop(); observer.join()`을 호출한다.

### 서버 관리 부담

`stdio`는 Claude Code가 프로세스 생명주기를 관리했지만, HTTP 서버는 별도로 시작/종료해야 한다.

완화책: `launchd plist`로 로그인 시 자동 시작, 크래시 시 자동 재시작을 구성한다.

### 로컬 포트 노출 — 수용 근거 명시

`127.0.0.1` 바인딩이므로 원격에서는 접근 불가하지만 같은 머신의 모든 로컬 프로세스에 노출된다.

**수용 근거**: 로컬 단일 사용자 workstation 전용, 민감한 데이터를 반환하지 않음(Obsidian 노트 텍스트), 원격 바인딩 없음. 이 조건이 바뀌면 재검토한다.

### Codex CLI 호환성

Codex CLI의 `type: http` MCP 지원 여부는 현재 미확인이다. Phase 0에서 검증한다.

---

## 6. 구현 계획

### Phase 0: Spike — 연결 가능성 검증 (선행 필수)

> 이전에 daemon mode를 제거한 이유가 "Claude Code는 command-based MCP만 지원"이었다. 이 가정이 틀렸는지 먼저 확인한다.

1. `mcp.run(transport="streamable-http")`로 서버를 로컬 실행
2. `~/.claude.json`에 `type: http` 항목 추가 후 Claude Code에서 tool 호출 확인
3. Codex CLI에서 동일 URL로 연결 테스트
4. `/mcp` 경로, 재시작 후 재연결 동작 확인

**이 단계가 실패하면 구현을 중단하고 대안을 재검토한다.**

### Phase 1: server.py transport 전환

1. FastMCP lifespan 훅에서 서버 시작 시 즉시 `_ensure_initialized()` 호출 (lazy init 제거)
2. lifespan shutdown 훅에서 watcher `observer.stop(); observer.join()` 호출
3. `mcp.run()` 을 `streamable-http`로 변경, `MCP_HOST` / `MCP_PORT` 환경변수 지원 추가
4. `build_index()` 호출부에 asyncio lock 또는 threading.Lock 적용

### Phase 2: 프로세스 관리

1. `start-server.sh` 작성 (uv 환경으로 서버 실행, 포트 충돌 시 명확한 오류 메시지)
2. macOS launchd plist 작성 (로그인 시 자동 시작, 크래시 시 자동 재시작)

### Phase 3: Claude Code 설정 업데이트

1. `~/.claude.json`의 `vault-decision` 항목을 `type: http`로 변경
2. README에 설정 가이드 업데이트 (서버 시작 방법, launchd 설치 방법 포함)

### Phase 4: 검증

1. 여러 Claude Code 세션에서 동시 tool 호출 테스트
2. `reindex` 후 다른 세션에서 결과 반영 확인
3. 서버 재시작 후 세션 자동 재연결 확인
4. watcher가 파일 변경을 감지하고 정상 인덱싱하는지 확인
5. 서버 강제 종료 후 launchd 자동 재시작 확인

---

## 7. 결정하지 않은 사항

| 항목 | 상태 | 비고 |
|------|------|------|
| Codex CLI 호환성 | **Phase 0에서 선행 검증 필요** | 구현 전 차단 조건 |
| 포트 기본값 | 8765 사용, 충돌 시 `MCP_PORT`로 오버라이드 | Phase 1에서 구현 |
| 인증 | 미도입 — 로컬 단일 사용자 수용 근거 명시됨 | 조건 변경 시 재검토 |
| ChromaDB thread-safety 범위 | Phase 1에서 lock 적용 후 부하 테스트로 검증 | |

---

## 8. 참고

- FastMCP 공식 문서: https://gofastmcp.com/deployment/running-server
- MCP spec (streamable-http): https://spec.modelcontextprotocol.io/specification/basic/transports/
- 현재 서버 코드: `vault-decision-mcp/server.py`
- daemon mode 제거 커밋: `286c400`
