# 02. vault 구조

vault는 두 개의 독립된 축으로 운영된다:

- **폴더 = 역할(role)** — 이 문서가 어떤 종류인지
- **frontmatter = 성숙도(quality)** — 이 문서가 얼마나 살아있는지

이 분리는 `Decision - 폴더와 frontmatter의 역할 분리.md`에 명시되어 있다.

## 폴더 구조

| 폴더 | 역할 | 인덱싱 |
|---|---|---|
| `00 Inbox/` | 미숙성 노트 임시 저장 | ❌ 제외 |
| `01 Notes/` | 활성 결정·노트 | ✅ |
| `02 Maps/` | MOC (Map of Content) — 주제 지도 | ✅ |
| `03 Sources/` | 외부 자료 (논문, 아티클, 발췌) | ✅ |
| `99 Archive/` | 폐기·대체된 문서 | ✅ (recursive) |
| `graphify-out/` | 자동 생성된 그래프 사이드카 | ✅ (제한적) |

`config.py:INDEX_PATTERNS`:

```python
INDEX_PATTERNS = [
    "01 Notes/*.md",
    "02 Maps/*.md",
    "03 Sources/*.md",
    "99 Archive/**/*.md",
    "graphify-out/GRAPH_REPORT.md",
    "graphify-out/wiki/*.md",
    "graphify-out/wiki/**/*.md",
]
```

→ `00 Inbox/`는 의도적으로 인덱싱 제외. 미숙성 노트는 의사결정 근거로 쓰면 안 된다.

## path_role — 폴더 + type의 통합 키

`indexer.py:infer_path_role`이 폴더 경로와 frontmatter type을 결합해 단일 키로 추론한다.

| 조건 | path_role |
|---|---|
| `01 Notes/Decision - *.md` + `type=decision` | `active_decision` |
| `01 Notes/*.md` 그 외 | `active_note` |
| `02 Maps/*.md` | `moc` |
| `03 Sources/*.md` | `source` |
| `99 Archive/**` | `archive` |
| `graphify-out/**` | `graph_sidecar` |
| `00 Inbox/` (인덱싱 안 됨) | (해당 없음) |
| `docs/plans/` | `planning` |
| 그 외 | `unknown` |

→ path_role은 검색 부스팅(`active_decision +0.05`, `archive −0.15` 등)과 권한 판정 버킷 분리(decisions/notes/historical_negative)의 1차 키로 쓰인다.

## 폴더별 활용 가이드

### `00 Inbox/`
- 임시 메모, 제텔카스텐 fleeting note, 정리 안 된 생각
- **인덱싱 제외**되므로 여기 둔 것은 MCP 검색에 안 잡힘
- 검토 후 `01 Notes/`로 옮기거나 삭제

### `01 Notes/` ⭐
- 가장 중요한 폴더. 결정과 노트의 1차 거주지
- **Decision**: 파일명 `Decision - 주제명.md`, `type: decision`. 권한 판정 받는 유일한 경로
- **Note**: 분석/조사/정리. `decision_candidates`가 있으면 candidate 버킷, 없으면 note_only 버킷

### `02 Maps/`
- MOC (Map of Content) — 특정 주제로 연결된 노트들의 색인
- `type: moc`, 보통 `## 결정`, `## 분석` 같은 섹션과 wiki 링크
- 부스팅 −0.02 (검색 결과로 직접 추천되기보단 탐색 진입점)

### `03 Sources/`
- 외부 자료의 발췌·번역·요약
- `type: source`, `sources: [URL 또는 출처]`
- 부스팅 −0.03 (출처일 뿐 결정 근거가 아님)

### `99 Archive/`
- **폐기되거나 대체된 문서를 보존**
- 본문/제목에 `superseded|deprecated|폐기|대체|보류|중단|아카이브` 등 부정 키워드가 있으면 `historical_negative` 신호 발생 → Claude가 진행 거부
- **삭제하지 말고 여기로 이동**해서 "역사적 거부 신호"로 활용

### `graphify-out/`
- graphify 도구가 자동 생성한 wiki/그래프 사이드카
- 부스팅 −0.08 (가장 후순위, 본 문서가 우선)

## 두 축의 의미

```
폴더 (역할)              frontmatter status (성숙도)
─────────────            ──────────────────────────
어디에 두는가?           얼마나 확정됐는가?
─────────────            ──────────────────────────
Inbox  → 임시            draft     → 작성 중
Notes  → 활성            hypothesis → 가설
Maps   → 색인            confirmed → 사실 확인됨
Sources → 출처           decided   → 결정 확정 ★
Archive → 폐기           archived  → 보존
```

이 두 축이 **독립적**이라는 게 핵심:
- `01 Notes/`에 있는 `status: draft` 결정 가능 (작성 중인 결정)
- `99 Archive/`에 있는 `status: decided` 가능 (한때 결정이었으나 폐기)

폴더로 성숙도를 표현하려고 하면(예: "완성된 건 Notes로, 미완은 Inbox로") 이 분리가 무너진다.

## 안전한 파일 읽기 (read_decision)

`server.py:_resolve_allowed_markdown`은 다음 prefix만 허용:

```python
ALLOWED_READ_PREFIXES = ("01 Notes/", "02 Maps/", "03 Sources/", "99 Archive/")
```

→ `00 Inbox/`, `templates/`, `docs/`, dotfile은 **읽기 차단**.
→ `Path.resolve()`로 vault root 밖 escape 차단 (symlink·`../` 공격 방지).

## 폴더 이동의 의미

| 이동 | path_role 변화 | 권한 영향 |
|---|---|---|
| `01 Notes/` → `99 Archive/` | active_decision/note → archive | 권한 박탈, historical_negative 후보 |
| `00 Inbox/` → `01 Notes/` | (인덱싱 X) → active | 검색 가능해짐 |
| `01 Notes/` 내부 이동 | 변화 없음 | 영향 없음 |

폴더 이동만으로 frontmatter 갱신 없이도 path_role이 자동 변경된다 — 단, **명시적 폐기는 `decision_status: superseded`도 함께 적는 게 권장**된다(이쪽은 폴더 위치와 무관하게 작동).
