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

### 4. 임베딩 모델 변경

`pyproject.toml`에 `chromadb==1.5.7`, `sentence-transformers==5.4.1` 버전 핀. 모델을 의식적으로 바꿀 때 `reindex(force=True)`로 인덱스 재구축. (P1.5에서 도입했던 startup mismatch 자동 검증은 Approach B에서 제거됨 — 사용자가 모델을 silent하게 바꾸는 시나리오 거의 0이라 가상 위협 방어로 판단.)

## 수동 도구

### `reindex(force=False)` MCP 도구

```python
@mcp.tool()
async def reindex(force: bool = False) -> str:
    async with _index_lock:
        if force:
            client.delete_collection(COLLECTION_NAME)
            _collection = client.get_or_create_collection(name=COLLECTION_NAME, embedding_function=fn)
            count = build_index(_collection, force=True)
        else:
            count = build_index(_ensure_initialized(), force=False)
    return f"Reindex complete. {count} documents indexed."
```

- `force=False` (기본) — mtime 비교 증분 갱신.
- `force=True` — 옛 collection 통째 삭제 후 재빌드.

도중 실패 시 broken state 가능성 있으나, 사용자 환경(1명, 1년 0~1회 호출)에선 단순 재호출로 복구 가능. (Phase 1.5.2 atomic swap 프로토콜 9-step + 1세대 보존은 Approach B에서 제거. 사유: 사용자 본인 평가 *"swap 기능을 구현할만큼 무중단 인덱싱 보장이 필요한 상황 아님"*.)

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
