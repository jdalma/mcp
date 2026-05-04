# 07. 트러블슈팅 + 운영

자주 발생하는 문제와 복구 방법, 운영 관찰 포인트를 정리한다.

## 인덱스 문제

### ChromaDB 손상 / 일관성 깨짐

증상:
- 서버 시작 시 ChromaDB 관련 예외
- `query`/`advise` 호출이 빈 결과만 반환하는데 vault엔 파일이 있음
- `stats`로 확인한 카운트가 vault 파일 수와 크게 다름

복구:

```bash
# 1) launchd 서비스 정지
launchctl unload ~/Library/LaunchAgents/com.vault-decision-mcp.plist

# 2) ChromaDB 디렉토리 삭제
rm -rf vault-decision-mcp/.chroma

# 3) 서비스 재시작 — lifespan에서 자동 full rebuild
launchctl load ~/Library/LaunchAgents/com.vault-decision-mcp.plist

# 4) 로그 확인
tail -f /tmp/vault-decision-mcp.log
```

→ vault 파일 자체엔 영향 없음. 인덱스는 vault에서 처음부터 다시 생성됨.

### 수동 강제 리빌드

서버를 안 끄고 인덱스만 다시 만들고 싶을 때:

```python
# Claude Code MCP에서 호출
mcp__vault-decision__reindex(force=True)
```

`force=False`(기본)는 mtime 비교로 변경분만 갱신. `force=True`는 기존 인덱스 전체 삭제 후 재구축.

### vault 변경이 인덱스에 반영 안 됨

증상: Obsidian에서 저장했는데 검색에 안 잡힘.

원인 후보:
1. **5초 디바운스 대기 중** — 잠시 후 재시도
2. **watchdog 죽음** — 서버 로그에서 `Vault watcher started` 이후 에러 확인. 없으면 서버 재시작
3. **mtime이 안 바뀜** — `touch -t` 등으로 과거 시각 설정 시. `reindex(force=True)`로 해결
4. **파일이 INDEX_PATTERNS에 안 매칭** — `00 Inbox/`, `templates/`, `docs/`는 의도적 제외 (`config.py:14`)

확인 명령:
```bash
# 인덱스 상태
mcp__vault-decision__stats

# 로그
tail -100 /tmp/vault-decision-mcp.log
```

## 임베딩 모델 문제

### 첫 시작 시 모델 다운로드 실패

증상: 서버 시작이 30초 이상 걸리거나 실패. HuggingFace 관련 예외.

원인: `snunlp/KR-SBERT-V40K-klueNLI-augSTS` 모델이 캐시에 없는데 네트워크 차단됨.

복구:

```bash
# 1) 네트워크 가능한 환경에서 모델 프리페치
uv run python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('snunlp/KR-SBERT-V40K-klueNLI-augSTS')"

# 2) 캐시 위치 확인
ls ~/.cache/huggingface/hub/

# 3) 오프라인 환경에 캐시 디렉토리 통째로 복사 후 서버 재시작
```

### 임베딩 모델 변경 후 결과가 이상함

증상: `VAULT_EMBEDDING_MODEL` 바꿨는데 검색 결과가 의미 매칭이 안 됨.

원인: 기존 인덱스는 옛 모델로 만든 임베딩이라 새 질문 임베딩과 차원·분포가 다름.

복구:

```bash
# 인덱스 전체 리빌드 필수
rm -rf vault-decision-mcp/.chroma
launchctl kickstart -k gui/$UID/com.vault-decision-mcp
```

또는 `reindex(force=True)`만으론 불충분 — embedding_function 자체가 collection에 바인딩되므로 collection을 삭제해야 한다.

## 권한 판정 결과가 예상과 다름

### "fresh decision인데 stale로 잡힘"

체크리스트 (`advisor.py:_is_stale_decision`):

```
□ status == "decided"        ← decided 외 값이면 stale
□ decision_status가 비어있음  ← superseded/deprecated/retired면 stale
□ revisit_when에 절대 날짜가 있다면 미래 날짜인지 확인
```

`revisit_when`의 날짜 형식은 **반드시 `YYYY-MM-DD` 4자리 연도 + 0 패딩**. `2026-8-1`, `2026/08/01`, `26-08-01`은 매칭 안 됨.

### "검색 결과가 비어있음 / 0.35 미만으로 잡힘"

threshold 0.35 미만이면 어느 버킷에도 안 들어가 `authority_level: none`이 된다.

원인 후보:
1. 임베딩 모델이 한국어 질문을 잘 매칭 못 함 → 질문을 결정 본문 키워드와 가깝게 다시 표현
2. **frontmatter `context`만 작성하고 본문에 안 적음** — frontmatter는 임베딩에 안 들어감 (`indexer.py:116-120`)
3. body에 핵심 키워드가 없음 → `## Decision` / `## Rationale` 섹션을 충실히 작성

### "충돌이 감지되지 않음"

체크:
1. **양쪽 결정 모두에 `conflicts_with` 적었는지** — 한쪽만 적으면 그쪽이 검색 1순위로 잡힐 때만 conflict 발동
2. `conflicts_with` 값에 다른 결정의 **title 또는 relative_path 일부**가 들어있는지 — 부분 문자열 매칭이지만 너무 짧으면 noise
3. 두 결정 모두 fresh인지 — 한쪽이 stale이면 conflict로 안 잡힘 (stale은 `supporting_evidence`로 강등)

### "destructive로 잘못 잡혀서 사용자 질문이 강제됨"

`classifier.py`는 명령형 동사 컨텍스트만 destructive로 분류한다. 그래도 잘못 잡히면 질문을 다음처럼 바꿔보자:

| ❌ 잘못 잡힘 | ✅ tradeoff로 잡힘 |
|---|---|
| "deploy 전략 어떻게?" | (이미 좁힌 패턴이라 잡힘) |
| "삭제해도 될까?" | "삭제 정책을 어떻게 정해야 할까?" |
| "롤백해야 해?" | "롤백 기준을 어떻게 세워야 할까?" |

근본적으론 정규식 한계 — 패턴이 더 추가되어야 하면 `classifier.py`의 `DESTRUCTIVE_PATTERNS`를 좁히는 방향으로 PR.

## 운영 관찰

### 호출 로그

```bash
tail -f ~/.vault-decision-mcp/calls.jsonl
```

- 모든 MCP tool 호출이 JSONL로 누적
- 필드: `timestamp`, `tool`, `inputs`, `result_summary`, `elapsed_ms`
- `result_summary.authority_level`로 vault가 어떤 권한을 떨어뜨렸는지 추적

⚠️ 현재 로그 로테이션 없음. 장기 운영 시 주기적 백업+삭제 필요:

```bash
# 매월 1일 cron 등에 등록 권장
mv ~/.vault-decision-mcp/calls.jsonl ~/.vault-decision-mcp/calls-$(date +%Y%m).jsonl
```

### 서버 헬스체크

```bash
# 프로세스 살아있나
launchctl list | grep vault-decision

# HTTP 응답
curl -s http://127.0.0.1:8765/mcp -X POST -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | head -50

# 인덱스 카운트
# (Claude Code에서)
mcp__vault-decision__stats
```

### vault 정기 점검

| 주기 | 작업 |
|---|---|
| 매주 | 새 결정 작성 시 `advise()`로 충돌 검사 |
| 매월 | `decision_timeline`으로 stale 결정 훑기 |
| 분기 | `stats` + `list_decisions`로 type=unknown 카운트 확인 (frontmatter 깨짐 발견) |
| 반기 | `decision_timeline`에서 1년 안 갱신된 결정 일괄 점검 |

## 테스트 실행

### 전체 테스트

```bash
cd vault-decision-mcp
uv run pytest tests/ -v
```

### 특정 모듈

```bash
uv run pytest tests/test_advisor.py -v
uv run pytest tests/test_indexer.py::test_conflicts_with_is_persisted_to_metadata -v
```

### 회귀 방지 테스트 추가 시

신규 동작은 반드시 테스트로 명시. 특히:
- 새 frontmatter 필드 → `test_indexer.py`에서 metadata 저장 검증
- 새 권한 룰 → `test_advisor.py`에서 authority_level + recommended_action 페어 검증
- 새 classifier 패턴 → `test_classifier.py`에서 false positive/negative 모두 검증

## 알려진 한계 (미해결)

| 항목 | 영향 | 우회 |
|---|---|---|
| `_ensure_initialized` race condition | 서버 시작 직후 동시 요청 시 모델 2회 로드 가능 | lifespan이 먼저 초기화하므로 실사용 영향 미미 |
| macOS PollingObserver 강제 | 1초 주기 stat 순회 — 1만 노트 규모에서 CPU 부담 | `VAULT_WATCHER=native` 환경변수로 강제 가능 (단 Obsidian sync 폴더에서 누락 위험) |
| call_logger 로그 로테이션 없음 | 장기 운영 시 GB 단위 성장 | 위 cron 절차로 수동 로테이션 |
| `mocs`, `sources` ChromaDB 메타에 저장만 됨 | 메타 크기 증가, 활용처 없음 | 무시 (vault 파일에서 직접 읽으면 됨) |
| `superseded_by` 구조화 필드 부재 | 대체 관계 자동 추적 불가 | 본문에 `## Superseded by [[...]]`로 수동 명시 |
