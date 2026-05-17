#!/usr/bin/env python3
"""1회용 vault frontmatter 마이그레이션 — canonical 필드 자동 주입.

확실(true) / 불확실(false) 양방향 자동 분류. 사용자 검토 0회.
dry-run 기본, --apply 플래그로 실 변경.

분류 룰:
- 01 Notes/Decision - *.md + status=decided → canonical: true
- 그 외 (00 Inbox/·99 Archive/는 스킵) → canonical: false

vault 데이터 무결성:
- YAML 파서는 *읽기 전용* (status 값 추출 목적).
- 쓰기는 텍스트 패치 — 정규식으로 기존 frontmatter 블록에 canonical 한 줄만
  append 또는 in-place 교체. 주석·인용 스타일·키 순서·커스텀 태그 보존.
- 파싱 실패 frontmatter는 skip + stderr 경고 + exit code 4로 차단.

Phase 4 종료 + dogfooding 1주 회귀 없으면 본 스크립트 삭제.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

INDEX_DIRS = ("01 Notes", "02 Maps", "03 Sources")
SKIP_DIRS = ("00 Inbox", "99 Archive")
DECISION_PREFIX = "Decision - "

FRONTMATTER_RE = re.compile(r"\A---\n((?:.*?\n)?)---\n", re.DOTALL)
CANONICAL_LINE_RE = re.compile(r"^canonical\s*:\s*\S+\s*$", re.MULTILINE)


def find_targets(vault: Path) -> list[Path]:
    targets: list[Path] = []
    for d in INDEX_DIRS:
        targets.extend(sorted((vault / d).rglob("*.md")))
    return targets


def classify_canonical(rel_path: str, meta: dict) -> bool:
    """확실(true) / 불확실(false) 분류."""
    name = Path(rel_path).name
    in_decision_dir = rel_path.startswith("01 Notes/") and name.startswith(DECISION_PREFIX)
    is_decided = meta.get("status") == "decided"
    return in_decision_dir and is_decided


def has_uncommitted_changes(vault: Path) -> bool:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(vault), "status", "--porcelain"],
            stderr=subprocess.DEVNULL,
        )
        return bool(out.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def read_frontmatter_meta(text: str) -> tuple[dict | None, bool]:
    """frontmatter를 읽기 전용으로 파싱.

    Returns:
      (dict, True)  — 정상 파싱
      ({}, True)    — frontmatter 없음 (신규 추가 대상)
      (None, False) — 파싱 실패 (skip 대상)
    """
    if not text.startswith("---\n"):
        return {}, True
    m = FRONTMATTER_RE.match(text)
    if not m:
        return None, False
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return None, False
    if not isinstance(meta, dict):
        return None, False
    return meta, True


def patch_canonical(text: str, canonical: bool) -> tuple[str, bool]:
    """텍스트 패치로 canonical 라인 삽입/교체. 원본 보존."""
    target_line = f"canonical: {str(canonical).lower()}"

    m = FRONTMATTER_RE.match(text)
    if not m:
        new_block = f"---\n{target_line}\n---\n"
        return new_block + text, True

    fm_inner = m.group(1)
    existing = CANONICAL_LINE_RE.search(fm_inner)

    if existing:
        if existing.group(0).strip() == target_line:
            return text, False
        new_fm = CANONICAL_LINE_RE.sub(target_line, fm_inner)
    else:
        if not fm_inner.endswith("\n"):
            fm_inner += "\n"
        new_fm = fm_inner + target_line + "\n"

    rest = text[m.end():]
    return f"---\n{new_fm}---\n{rest}", True


def main() -> int:
    parser = argparse.ArgumentParser(prog="migrate_canonical")
    parser.add_argument("--apply", action="store_true",
                        help="실제로 파일 수정 (기본은 dry-run)")
    parser.add_argument("--vault", default=os.environ.get("VAULT_PATH"))
    args = parser.parse_args()

    if not args.vault:
        print("ERROR: --vault or VAULT_PATH required", file=sys.stderr)
        return 2

    vault = Path(args.vault).expanduser().resolve()
    if not vault.is_dir():
        print(f"ERROR: vault not found: {vault}", file=sys.stderr)
        return 2

    if not (vault / ".git").exists():
        print("WARNING: vault is not a git repo. 백업 권장.", file=sys.stderr)
    elif has_uncommitted_changes(vault):
        print("ERROR: vault has uncommitted changes. Commit/stash first.", file=sys.stderr)
        return 3

    targets = find_targets(vault)
    summary = {
        "true": 0,
        "false": 0,
        "skipped_already_set": 0,
        "skipped_archive_inbox": 0,
        "parse_failed": 0,
    }
    changes: list[tuple[str, bool]] = []
    parse_failures: list[str] = []

    for f in targets:
        rel = str(f.relative_to(vault))
        if any(rel.startswith(d + "/") for d in SKIP_DIRS):
            summary["skipped_archive_inbox"] += 1
            continue
        text = f.read_text(encoding="utf-8")
        meta, ok = read_frontmatter_meta(text)
        if not ok:
            summary["parse_failed"] += 1
            parse_failures.append(rel)
            continue
        canonical = classify_canonical(rel, meta)
        new_text, changed = patch_canonical(text, canonical)
        if not changed:
            summary["skipped_already_set"] += 1
            continue
        summary["true" if canonical else "false"] += 1
        changes.append((rel, canonical))
        if args.apply:
            f.write_text(new_text, encoding="utf-8")

    mode = "APPLIED" if args.apply else "DRY-RUN"
    print(f"=== {mode} ===")
    for rel, c in changes:
        print(f"  [canonical={c}] {rel}")

    if parse_failures:
        print()
        print(f"=== PARSE FAILURES ({len(parse_failures)} files, skipped) ===",
              file=sys.stderr)
        for rel in parse_failures:
            print(f"  [skip] {rel}", file=sys.stderr)

    print()
    print(f"true: {summary['true']}, false: {summary['false']}, "
          f"already_set: {summary['skipped_already_set']}, "
          f"skipped(00/99): {summary['skipped_archive_inbox']}, "
          f"parse_failed: {summary['parse_failed']}")

    if summary["parse_failed"] > 0:
        print()
        print("ERROR: parse failures detected. Fix the affected files first and re-run.",
              file=sys.stderr)
        return 4

    if not args.apply:
        print()
        print("Re-run with --apply to write changes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
