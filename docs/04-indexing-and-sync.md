# 04. 인덱싱과 동기화

vault의 마크다운 파일이 어떻게 ChromaDB에 동기화되는지, watchdog → indexer → ChromaDB 체인을 정리한다.

## 동기화 체인 전체

```
[1] vault의 .md 파일 변경 (Obsidian 저장, git checkout, 외부 편집)
        ↓
[2] watchdog Observer (백그라운드 데몬 스레드)
        ↓ 이벤트: on_modified / on_created / on_deleted
[3] VaultChangeHandler._schedule_reindex
        ↓ 5초 디바운스 (threading.Timer)
[4] _reindex_sync 콜백
        ↓ asyncio.run_coroutine_threadsafe
[5] 메인 asyncio 루프의 _reindex coroutine
        ↓ async with _index_lock
[6] indexer.build_index(collection)
        ↓ mtime 비교로 변경된 파일만 추림
[7] collection.upsert / collection.delete
        ↓ 임베딩 자동 재계산 (KR-SBERT)
[8] ChromaDB .chroma/ 디스크 갱신
```

## 단계별 구현

### [2] watchdog Observer 시작

`watcher.py:start_watcher`:

```python
def start_watcher(vault_path, reindex_callback) -> Observer:
    handler = VaultChangeHandler(reindex_callback)
    observer_cls = _observer_class()  # macOS=Polling, Linux=native
    observer = observer_cls()
    observer.schedule(handler, str(vault_path), recursive=True)
    observer.daemon = True
    observer.start()
```

`_observer_class` 선택 로직:
- `VAULT_WATCHER=native` → Observer (FSEvents/inotify)
- `VAULT_WATCHER=polling` → PollingObserver
- macOS 기본 → PollingObserver (FSEvents가 iCloud/Obsidian sync에서 누락되는 문제 회피)
- Linux/Windows 기본 → Observer (native)

### [3] 디바운스 핸들러

`watcher.py:VaultChangeHandler`:

```python
DEBOUNCE_SECONDS = 5.0

def _schedule_reindex(self):
    with self._lock:
        if self._timer is not None:
            self._timer.cancel()           # 기존 타이머 취소
        self._timer = threading.Timer(DEBOUNCE_SECONDS, self._do_reindex)
        self._timer.start()

def on_modified(self, event):
    if not event.is_directory and event.src_path.endswith(".md"):
        self._schedule_reindex()
```

핵심: **마지막 변경 5초 후 한 번만** 재인덱싱. Obsidian의 빠른 연속 저장이나 git checkout으로 100개 파일이 동시 변경돼도 한 번만 처리.

`.md` 확장자만 필터. on_modified / on_created / on_deleted 모두 같은 디바운스 큐로 합쳐짐.

### [4] 스레드 → asyncio 다리

`server.py:lifespan`:

```python
loop = asyncio.get_running_loop()

async def _reindex():
    async with _index_lock:
        build_index(_collection)

def _reindex_sync():
    asyncio.run_coroutine_threadsafe(_reindex(), loop)

_observer = start_watcher(get_vault_path(), _reindex_sync)
```

watchdog 콜백은 **다른 스레드**(Observer 데몬)에서 실행되는데 ChromaDB 작업은 메인 asyncio 루프에서 해야 한다. `run_coroutine_threadsafe`로 다리를 놓고, `_index_lock`으로 수동 `reindex` 호출과 직렬화.

### [6] mtime 비교 증분 인덱싱

`indexer.py:build_index`:

```python
# 1. 현재 vault 파일 수집
files = collect_vault_files(vault)        # INDEX_PATTERNS glob
current_files = {rel: str(stat.st_mtime) for ...}

# 2. force=True면 기존 인덱스 전체 삭제
if force:
    existing = collection.get()
    if existing["ids"]:
        collection.delete(ids=existing["ids"])

# 3. 기존 인덱스의 mtime과 비교
existing = collection.get(include=["metadatas"])
existing_mtimes = {doc_id: meta.get("mtime", "") for ...}

# 4. 삭제된 파일 제거
deleted = set(existing_mtimes) - set(current_files)
if deleted:
    collection.delete(ids=list(deleted))

# 5. 변경/추가된 파일만 필터
files_to_index = [
    f for f in files
    if rel not in existing_mtimes or existing_mtimes[rel] != current_mtime
]

# 6. 파싱 + ChromaDB upsert
for file_path in files_to_index:
    text = file_path.read_text()
    meta, body = parse_markdown(text)
    doc = prepare_document(file_path, meta, body)
    ...
collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
```

**핵심**: 변경 안 된 파일은 임베딩 재계산도 안 함. KR-SBERT는 무거우니 이게 성능의 핵심. 파일 1000개 중 1개만 바뀌어도 1개만 임베딩.

### [7] ChromaDB upsert 동작

```python
collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
```

- `id`는 vault 상대경로 (예: `01 Notes/Decision - X.md`) → 안정적 식별자
- `upsert`는 같은 id면 덮어쓰기, 새 id면 추가
- 임베딩은 collection 생성 시 등록한 `embedding_function`(KR-SBERT)이 자동 호출
- `documents`는 `# title\ntype | status | tags\n\nbody` 형식의 검색용 텍스트
- `metadatas`엔 frontmatter 추출값 + path_role + content_hash + mtime

## 동기화의 실제 보장 수준

| 시나리오 | 동작 |
|---|---|
| Obsidian에서 파일 저장 | 5초 후 자동 인덱스 갱신 |
| 빠른 연속 저장 10번 | 마지막 저장 5초 후 1번만 인덱싱 |
| 파일 삭제 | 5초 후 ChromaDB에서도 삭제 |
| 파일명 변경 (rename) | 옛 id 삭제 + 새 id 추가 |
| 폴더 통째로 이동 | 재귀 감시로 전부 감지, mtime 비교로 정상 처리 |
| git checkout 100개 변경 | 5초 후 mtime 다른 100개만 임베딩 |
| watchdog 자체가 죽음 | `reindex` MCP 도구로 수동 갱신 가능 |
| 서버 재시작 | lifespan에서 build_index 강제 실행 → 누락분 동기화 |
| advise 호출 시점 stale 판정 | 인덱스와 무관, `revisit_when`은 검색 시점 평가 |

## 안전장치

### vault root 외부 symlink 차단

`collect_vault_files`는 수집 후 각 파일의 `resolve()` 결과가 vault root 안에 있는지 검증한다. vault 안에서 vault 밖을 가리키는 symlink가 있으면 경고 로그 후 제외된다.

```python
try:
    resolved = f.resolve(strict=False)
    resolved.relative_to(vault_root)
except ValueError:
    logger.warning("Skipping path that escapes vault root: %s", f)
    continue
```

→ vault 외부 민감 파일이 ChromaDB에 인덱싱되어 `query` 도구로 노출되는 사고를 방지.

### YAML frontmatter 파싱 실패 시 경고

`parse_markdown`은 YAML 파싱이 실패하거나 mapping이 아닌 경우 빈 dict로 fallback하지만 **반드시 경고 로그를 남긴다**.

```
WARNING: YAML frontmatter parse failed for /vault/01 Notes/Decision - X.md: ...
```

→ 사용자가 frontmatter 깨진 줄 모르고 결정이 권한 없이 묻히는 상황 방지. `stats` 도구로 type=unknown 카운트를 확인하면 간접 발견 가능.

## 동기화의 한계

### 1. 5초 지연
Obsidian에서 저장 직후 즉시 검색하면 옛 내용이 잡힐 수 있음. 즉시 반영하려면 `reindex` MCP 도구 호출.

### 2. macOS PollingObserver 폴링 주기
native FSEvents보다 늦고 CPU 약간 더 씀. 동기 폴더에서 안정성을 위해 의도적 선택.

### 3. mtime 정확도
파일시스템이 mtime을 안 바꾸는 도구로 수정하면(`touch -t` 등) 인덱싱 누락 가능. `reindex(force=True)`로 전체 리빌드.

### 4. 임베딩 모델 동기화 — startup mismatch 검증 (P1.5)

P1.5에서 `pyproject.toml`에 `chromadb==1.5.7`, `sentence-transformers==5.4.1` 버전 핀.

`_init_collection`은 collection 메타에 `embedding_model_id`를 저장한다. startup 시 stored 값과 현재 `VAULT_EMBEDDING_MODEL` env가 다르면 `_check_embedding_model_mismatch`가 logger.warning으로 알린다:

```
WARNING: Embedding model mismatch: index was built with 'old/model' but
current model is 'new/model'. Run reindex(force=True) to rebuild.
```

→ 사용자가 모델을 바꿨음을 명시적으로 인지 + `reindex(force=True)`로 swap 프로토콜 트리거. silent re-embedding 차단.

## 수동 도구

### `reindex(force=False)` MCP 도구

```python
@mcp.tool()
async def reindex(force: bool = False) -> str:
    if force:
        await _swap_collection()  # 신규: atomic swap 프로토콜
        return "Reindex complete via swap protocol."
    async with _index_lock:
        count = build_index(_ensure_initialized(), force=False)
    return f"Reindex complete. {count} documents indexed."
```

- `force=False` (기본) — mtime 비교 증분 갱신 (기존 흐름).
- `force=True` — **atomic swap 프로토콜**(`_swap_collection`) 호출. 옛 컬렉션 보존 상태에서 신규 컬렉션 빌드 → 검증 → 핸들 교체. 검증 실패 시 자동 롤백.

## Swap 프로토콜 (`_swap_collection`)

P1.5.2 도입. *"기존 컬렉션을 먼저 지우고 새로 만드는"* 옛 방식이 도중 실패 시 broken state를 남기는 문제 해소.

### 9-step 시퀀스

```
1. async with _index_lock        # 직렬화
2. watcher.pause()                # 파일 변경 콜백 차단
3. client.get_or_create_collection(
       name=f"{COLLECTION_NAME}_{ts_ms}",
       embedding_function=embedding_fn,
   )
4. build_index(new_col, force=True)  # 신규 컬렉션에 vault 전체 인덱싱
5. validate(new_col)                  # 선택적 검증 콜백
   - 실패 시 → client.delete_collection(new_name) + watcher.resume() + return
6. delete_collection(_previous_collection_name)  # 2세대 전 정리
7. _collection = new_col          # 글로벌 핸들 교체
   _previous_collection_name = old.name  # 옛 1세대 보존
8. watcher.resume()
9. lock 해제 (context manager)
```

### chromadb 라이브러리 제약

- `collection.modify(name=...)` 의 name 파라미터가 **존재하지 않음**. 따라서 *"기존 컬렉션 rename"* 은 불가능. swap = "신규 생성 + 핸들 교체"만 가능.
- 로컬 `PersistentClient`는 동일 persistence 경로에 process-safe 동시 writer 보장 안 함. 따라서 swap은 단일 프로세스 내에서만 안전. `_index_lock` + `watcher.pause()` 가 이 제약을 보완.

### 1세대 보존의 의미

옛 컬렉션을 **즉시 삭제하지 않고** `_previous_collection_name`에 보관 → 다음 swap 시점에 *"옛 옛"*(2세대 전) 컬렉션을 정리. 이유:

- 진행 중 advise/query 요청이 옛 컬렉션 핸들을 캡처해 잡고 있을 수 있음. 그 응답이 끝나기 전에 옛 컬렉션을 삭제하면 race condition.
- 1세대 보존은 *"진행 중 요청이 자기 응답까지는 옛 핸들로 정상 완료, 다음 요청부터 새 핸들"* 보장.

### 검증 콜백 (`validate` 인자)

`_swap_collection(*, validate=None)` 호출 시 `validate(new_col)` 가 False/falsy 반환하면 swap 취소 + 신규 컬렉션 삭제. `_collection` 글로벌은 옛 핸들 그대로 유지.

권장 검증 게이트 3개 (Phase 1.5.6 production rebuild에서 활용):
1. **file count**: `new_col.count()` ↔ vault의 INDEX_PATTERNS 매칭 파일 수 일치
2. **content_hash**: 각 파일 메타의 `content_hash` 일치
3. **regression set**: `tests/test_regression.py`의 10건이 신규 컬렉션 위에서도 expected `authority_level` 반환 (10건은 production 인덱스 의존이라 unit test에선 conditional skip)

### 롤백 경로

검증 실패 또는 build_index 예외 시:
- `client.delete_collection(new_name)`
- `watcher.resume()`
- `_collection` 옛 핸들 유지 — 사용자에게 보이는 vault advice는 끊김 없음

### `watcher.pause()` / `resume()`

`watcher.py` 모듈 레벨 `_paused` 플래그 + `threading.Lock`. handler의 `on_modified`/`on_created`/`on_deleted`에서 `_paused` True면 즉시 return. swap 도중 vault에 변경이 들어와도 indexing 큐에 안 들어가서 collision 차단.

⚠️ chromadb 라이브러리는 watchdog Observer의 `unschedule_all()` 같은 일급 pause API를 제공하지 않음. 위 모듈 플래그 방식이 우회.

### 서버 재시작 시 자동 동작

`server.py:_init_collection`이 lifespan에서 한 번 실행되며 내부적으로 `build_index`를 호출해 인덱스와 디스크 상태를 정합화. 서버가 멈춘 사이 vault가 바뀌어도 시작 시 누락분이 따라잡힌다.

## 스레드/락 모델

```
[Observer 데몬 스레드]
        ↓ on_modified
[Timer 스레드 (5초)]
        ↓ run_coroutine_threadsafe
[메인 asyncio 루프]
        ↓ async with _index_lock
[build_index 동기 함수]
        ↓
[ChromaDB I/O]
```

- `_index_lock`은 asyncio.Lock — watchdog 자동 인덱싱과 수동 `reindex` 호출이 충돌하지 않도록 직렬화
- ChromaDB 자체는 sqlite 기반이라 단일 프로세스 내 동시 접근은 ChromaDB가 처리
- 임베딩 함수(KR-SBERT)는 thread-safe (sentence-transformers 내부 처리)

## 정리

**watchdog**: vault에 변화가 있다는 **신호만** 보낸다.
**indexer.build_index**: 디스크 vault와 ChromaDB의 차이를 mtime 기준으로 계산해서 동기화한다.
**ChromaDB.upsert**: 변경분에 대해 KR-SBERT 임베딩을 자동 재생성하고 저장한다.

세 단계가 분리돼 있어서:
- 파일 감시 없이도 `reindex` MCP 도구로 수동 호출 가능
- 첫 서버 시작 시 watchdog 없이도 lifespan이 build_index를 한 번 돌려 초기 동기화
- watchdog가 깨져도 정기적으로 `reindex` 호출하면 복구 가능
