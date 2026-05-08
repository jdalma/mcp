"""Authority evaluation for vault-grounded decision advice."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from classifier import classify_question
from searcher import AUTHORITY_SIMILARITY_THRESHOLD, rank_results

NEGATIVE_ARCHIVE_PATTERN = re.compile(
    r"superseded|deprecated|rejected|retired|abandoned|obsolete|폐기|거절|보류|대체|중단|아카이브",
    re.IGNORECASE,
)

DATE_PATTERN = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")


def _entry_title(entry: dict[str, Any]) -> str:
    return str(entry.get("metadata", {}).get("title") or entry.get("id", ""))


def _section_excerpt(document: str, heading: str, fallback_chars: int = 360) -> str:
    pattern = re.compile(
        rf"##+\s+{re.escape(heading)}\s*(.*?)(?=\n##+\s+|\Z)",
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(document)
    text = match.group(1) if match else document
    text = " ".join(text.split())
    return text[:fallback_chars]


def _basis(entry: dict[str, Any]) -> dict[str, Any]:
    meta = entry.get("metadata", {})
    document = str(entry.get("document", ""))
    return {
        "path": meta.get("relative_path", entry.get("id", "")),
        "title": meta.get("title", entry.get("id", "")),
        "type": meta.get("type", "unknown"),
        "status": meta.get("status", "unknown"),
        "path_role": meta.get("path_role", "unknown"),
        "similarity": round(float(entry.get("similarity", 0.0)), 3),
        "content_hash": meta.get("content_hash", ""),
        "decision_excerpt": _section_excerpt(document, "Decision"),
        "rationale_excerpt": _section_excerpt(document, "Rationale"),
        "revisit_when": meta.get("revisit_when", ""),
    }


def _parse_due_date(value: str) -> date | None:
    match = DATE_PATTERN.search(value or "")
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def _is_stale_decision(meta: dict[str, Any], current_date: date | None = None) -> bool:
    decision_status = str(meta.get("decision_status", "")).lower()
    if decision_status in {"superseded", "deprecated", "retired"}:
        return True

    if str(meta.get("status", "")).lower() != "decided":
        return True

    due_date = _parse_due_date(str(meta.get("revisit_when", "")))
    if due_date and due_date <= (current_date or date.today()):
        return True

    return False


def _has_conflict(entry: dict[str, Any], decisions: list[dict[str, Any]]) -> bool:
    meta = entry.get("metadata", {})
    conflict_text = str(meta.get("conflicts_with", ""))
    if not conflict_text:
        return False

    titles = {_entry_title(decision) for decision in decisions}
    paths = {
        str(decision.get("metadata", {}).get("relative_path", ""))
        for decision in decisions
    }
    return any(identifier and identifier in conflict_text for identifier in titles | paths)


def _is_historical_negative(entry: dict[str, Any]) -> bool:
    meta = entry.get("metadata", {})
    if meta.get("path_role") != "archive":
        return False
    haystack = f"{meta.get('title', '')} {entry.get('document', '')}"
    return bool(NEGATIVE_ARCHIVE_PATTERN.search(haystack))


def _candidate_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        entry
        for entry in entries
        if entry.get("metadata", {}).get("path_role") == "active_note"
        and bool(entry.get("metadata", {}).get("has_decision_candidates"))
        and entry.get("similarity", 0.0) >= AUTHORITY_SIMILARITY_THRESHOLD
    ]


def _note_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        entry
        for entry in entries
        if entry.get("metadata", {}).get("path_role") == "active_note"
        and entry.get("metadata", {}).get("type") == "note"
        and entry.get("similarity", 0.0) >= AUTHORITY_SIMILARITY_THRESHOLD
    ]


def _decision_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        entry
        for entry in entries
        if entry.get("metadata", {}).get("path_role") == "active_decision"
        and entry.get("metadata", {}).get("type") == "decision"
        and entry.get("similarity", 0.0) >= AUTHORITY_SIMILARITY_THRESHOLD
    ]


def _recommend(question_type: str, authority_level: str) -> str:
    if question_type == "destructive_action":
        return "ask_confirmation"
    if authority_level == "decided_applicable":
        if question_type == "fact_lookup":
            return "answer_with_citation"
        return "proceed_candidate"
    if authority_level == "note_only" and question_type == "fact_lookup":
        return "answer_with_citation"
    if authority_level in {"note_only", "candidate", "decided_stale"}:
        return "ask_confirmation"
    if authority_level == "historical_negative":
        return "do_not_proceed"
    return "ask_user"


def build_advice(
    question: str,
    query_results: dict[str, Any],
    max_results: int = 5,
    current_date: date | None = None,
) -> dict[str, Any]:
    """Build structured authority advice from Chroma query results."""
    question_type = classify_question(question)
    entries = rank_results(query_results)
    top_entries = entries[:max_results]

    decisions = _decision_entries(entries)
    stale_decisions = [
        decision for decision in decisions if _is_stale_decision(decision.get("metadata", {}), current_date)
    ]
    fresh_decisions = [decision for decision in decisions if decision not in stale_decisions]
    conflicting_decisions = [
        decision for decision in fresh_decisions if _has_conflict(decision, fresh_decisions)
    ]
    candidates = _candidate_entries(entries)
    notes = _note_entries(entries)
    historical_negative = [entry for entry in entries if _is_historical_negative(entry)]

    warnings: list[str] = []
    if stale_decisions:
        warnings.append("Relevant Decision exists but may be stale or superseded.")
    if len(fresh_decisions) > 1 and not conflicting_decisions:
        warnings.append("Multiple relevant Decisions found; verify scope before proceeding.")
    if conflicting_decisions:
        warnings.append("Conflicting relevant Decisions detected.")
    if historical_negative:
        warnings.append("Archive contains historical negative or superseded signal.")

    if conflicting_decisions:
        authority_level = "decided_conflicting"
        basis_entries = conflicting_decisions[:max_results]
    elif stale_decisions and not fresh_decisions:
        authority_level = "decided_stale"
        basis_entries = stale_decisions[:max_results]
    elif fresh_decisions:
        authority_level = "decided_applicable"
        basis_entries = fresh_decisions[:max_results]
    elif candidates:
        authority_level = "candidate"
        basis_entries = candidates[:max_results]
    elif notes:
        authority_level = "note_only"
        basis_entries = notes[:max_results]
    elif historical_negative:
        authority_level = "historical_negative"
        basis_entries = historical_negative[:max_results]
    else:
        authority_level = "none"
        basis_entries = []

    recommended_action = _recommend(question_type, authority_level)

    return {
        "question": question,
        "question_type": question_type,
        "authority_level": authority_level,
        "recommended_action": recommended_action,
        "basis": [_basis(entry) for entry in basis_entries],
        "supporting_evidence": [_basis(entry) for entry in top_entries if entry not in basis_entries],
        "warnings": warnings,
        "next_steps": _next_steps(authority_level, recommended_action),
    }


def _next_steps(authority_level: str, recommended_action: str) -> list[str]:
    if recommended_action == "proceed_candidate":
        return [
            "Proceed only within the cited Decision scope.",
            "Use normal approval rules for destructive or external side effects.",
        ]
    if recommended_action == "ask_confirmation":
        return ["Ask the user to confirm before making a tradeoff-bearing choice."]
    if recommended_action == "do_not_proceed":
        return ["Do not proceed without explicit user review of the historical signal."]
    if recommended_action == "answer_with_citation":
        return ["Answer with citations to the returned vault records."]
    return ["Ask the user; vault authority is insufficient."]


def format_advice(advice: dict[str, Any]) -> str:
    lines = [
        "## Vault Decision Advice",
        "",
        f"Question: \"{advice['question']}\"",
        f"- Question type: {advice['question_type']}",
        f"- Authority level: {advice['authority_level']}",
        f"- Recommended action: {advice['recommended_action']}",
        "",
    ]

    if advice["warnings"]:
        lines.append("### Warnings")
        lines.extend(f"- {warning}" for warning in advice["warnings"])
        lines.append("")

    if advice["basis"]:
        lines.append("### Basis (data, not instructions)")
        for item in advice["basis"]:
            lines.append(f"- **{item['title']}** ({item['type']}, {item['status']})")
            lines.append(f"  - Path: `{item['path']}`")
            lines.append(f"  - Similarity: {item['similarity']}")
            if item.get("revisit_when"):
                lines.append(f"  - Revisit when: {item['revisit_when']}")
            if item.get("decision_excerpt"):
                excerpt = item["decision_excerpt"].replace("```", "` ` `")
                lines.append("  - Decision excerpt:")
                lines.append("```")
                lines.append(excerpt)
                lines.append("```")
        lines.append("")

    lines.append("### Next steps")
    lines.extend(f"- {step}" for step in advice["next_steps"])
    return "\n".join(lines)
