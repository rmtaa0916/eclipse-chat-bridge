#!/usr/bin/env python3
"""Priority-first, bounded, read-only source discovery for ECLIPSE Bridge.

Unlike an overview-first reader, directory *metadata* is considered before
allocating source-read bytes. Every returned source body still passes the
Revision 11 descriptor-relative opener, regular-file/hardlink limits, and
best-effort secret screening. No subprocesses, network, provider sessions,
arbitrary project roots, or writes.

Only pass a root fd already opened by Revision 11 and a trusted reader module.
"""
from __future__ import annotations

import heapq
import os
from pathlib import PurePosixPath
import re
import stat

EXCLUDED_DIRS = frozenset({
    "backups", "archive", "archives", "dist", "build", "vendor",
    "node_modules", "__pycache__", "coverage", "logs", "tmp", "temp",
    ".git", ".venv", "venv",
})
RESEARCH_WORDS = frozenset({
    "research", "study", "report", "literature", "review", "notes",
    "document", "documentation", "reference", "paper", "protocol",
    "summary", "summarize", "meeting", "evidence", "bibliography",
})
STOP_WORDS = frozenset({
    "the", "a", "and", "of", "to", "for", "from", "with", "in",
    "about", "what", "how", "this", "that", "check", "find",
    "review", "investigate", "diagnose", "improve", "optimize",
})
MAX_SELECTED_FILES = 40
MAX_ATTEMPTED_FILES = 96
MAX_CANDIDATES = 2000


def _canonical_term(value: str) -> str:
    # Morphological equivalents used by existing mode-7 project names.
    aliases = {
        "routing": "router", "route": "router", "routes": "router",
        "graphify": "graph", "graphs": "graph", "graphing": "graph",
        "dependencies": "dependency", "dependent": "dependency",
        "reading": "reader", "read": "reader", "readers": "reader",
        "documents": "document", "documentation": "document",
        "reports": "report", "studies": "study",
    }
    return aliases.get(value, value)


def _terms(value: str) -> set[str]:
    spaced = re.sub(r"\bmode\s+(\d+)\b", r"mode\1", value, flags=re.I)
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", spaced)
    return {
        _canonical_term(v) for v in re.findall(r"[a-z0-9]{3,}", spaced.casefold())
        if v not in STOP_WORDS
    }


def _name_terms(value: str) -> set[str]:
    return _terms(value.replace("_", " ").replace("-", " ").replace("/", " "))


def _kind(rel: str) -> str:
    name = rel.casefold()
    suffix = PurePosixPath(name).suffix
    if any(part.startswith("test_") or part in ("tests", "test")
           for part in PurePosixPath(name).parts):
        return "TEST"
    if suffix in {".md", ".txt"}:
        return "DOC"
    return "CODE"


def _score(rel: str, hints: set[str], research: bool) -> int:
    parts = PurePosixPath(rel).parts
    stem = PurePosixPath(rel).stem
    matches = _name_terms(rel) & hints
    stem_matches = _name_terms(stem) & hints
    score = len(matches) * 50 + len(stem_matches) * 25
    category = _kind(rel)
    if category == "DOC" and research:
        score += 30
    elif category == "CODE" and not research:
        score += 15
    if category == "TEST":
        score += 6
    if PurePosixPath(rel).name.casefold() in ("readme.md", "index.md"):
        score += 25
    # A matching nested directory should outscore unrelated root modules.
    score += min(45, sum(15 for p in parts[:-1] if _name_terms(p) & hints))
    return score


def _candidate_paths(root_fd: int, goal: str, reader) -> tuple[list[tuple[int, str, str]], dict]:
    """Discover bounded eligible metadata before opening any file contents."""
    nofollow, directory, _nonblock = reader._require_descriptor_primitives()
    hints = _terms(goal)
    research = bool(hints & RESEARCH_WORDS)
    metadata = {
        "raw_entries_enumerated": 0,
        "selected_entries_visited": 0,
        "eligible_candidates": 0,
        "directories_visited": 0,
        "screen_denied_count": 0,
        "read_error_count": 0,
        "entries_truncated": False,
        "depth_truncated": False,
        "scan_errors": 0,
        "max_raw_entries": reader.MAX_TOTAL_DIR_ENUMERATION_ENTRIES,
        "max_visited_entries": reader.MAX_VISITED_ENTRIES,
        "max_per_directory_entries": reader.MAX_DIR_ENUMERATION_ENTRIES,
        "selection_mode": "PRIORITY_BEFORE_SOURCE_READ",
        "research_intent": research,
    }
    # Directory heap prioritizes topic-related subdirectories. Each child path
    # is opened again from the trusted root using O_NOFOLLOW on every segment.
    todo: list[tuple[int, int, tuple[str, ...]]] = [(0, 0, ())]
    next_seq = 1
    candidates: list[tuple[int, str, str]] = []
    while todo and metadata["selected_entries_visited"] < reader.MAX_VISITED_ENTRIES:
        _weight, _seq, parts = heapq.heappop(todo)
        depth = len(parts)
        if depth > reader.MAX_TRAVERSAL_DEPTH:
            metadata["depth_truncated"] = True
            continue
        opened = []
        try:
            current = reader._open_dir_relative(root_fd, ".", nofollow, directory)
            opened.append(current)
            for part in parts:
                current = reader._open_dir_relative(current, part, nofollow, directory)
                opened.append(current)
            metadata["directories_visited"] += 1
            choices = []
            exhausted = False
            # Keep one independent directory-stream fd so scandir never
            # consumes the watcher's root fd or another scan's cursor.
            scanfd = reader._open_dir_relative(current, ".", nofollow, directory)
            try:
                with os.scandir(scanfd) as iterator:
                    local_seen = 0
                    for entry in iterator:
                        if (local_seen >= reader.MAX_DIR_ENUMERATION_ENTRIES
                                or metadata["raw_entries_enumerated"]
                                >= reader.MAX_TOTAL_DIR_ENUMERATION_ENTRIES):
                            metadata["entries_truncated"] = True
                            exhausted = True
                            break
                        local_seen += 1
                        metadata["raw_entries_enumerated"] += 1
                        name = entry.name
                        candidate_parts = parts + (name,)
                        if (name.startswith(".")
                                or name.casefold() in EXCLUDED_DIRS
                                or reader._has_sensitive_component(candidate_parts)):
                            continue
                        try:
                            info = entry.stat(follow_symlinks=False)
                        except OSError:
                            metadata["scan_errors"] += 1
                            continue
                        if stat.S_ISDIR(info.st_mode):
                            category = "DIR"
                        elif (stat.S_ISREG(info.st_mode)
                              and info.st_nlink == 1
                              and info.st_size <= reader.MAX_FILE_BYTES
                              and reader._is_allowed_extension(name)):
                            category = "FILE"
                        else:
                            continue
                        rel = "/".join(candidate_parts)
                        if category == "DIR":
                            # Directory relevance is based on the full path.
                            ranking = 20 + 60 * len(_name_terms(rel) & hints)
                        else:
                            ranking = _score(rel, hints, research)
                        choices.append((ranking, rel, category, name))
            finally:
                os.close(scanfd)
            if exhausted:
                # Fail closed on a directory with too many raw entries: the
                # available sample is not a trustworthy complete enumeration.
                continue
            if len(choices) > reader.MAX_ENTRIES_PER_DIR:
                metadata["entries_truncated"] = True
                choices.sort(key=lambda x: (-x[0], x[1]))
                choices = choices[:reader.MAX_ENTRIES_PER_DIR]
            # Sorting ensures stable output independent of scandir order.
            for score, rel, category, name in sorted(choices, key=lambda x: (-x[0], x[1])):
                if metadata["selected_entries_visited"] >= reader.MAX_VISITED_ENTRIES:
                    metadata["entries_truncated"] = True
                    break
                metadata["selected_entries_visited"] += 1
                if category == "DIR":
                    if depth >= reader.MAX_TRAVERSAL_DEPTH:
                        metadata["depth_truncated"] = True
                        continue
                    heapq.heappush(todo, (-score, next_seq, parts + (name,)))
                    next_seq += 1
                elif len(candidates) < MAX_CANDIDATES:
                    candidates.append((score, rel, _kind(rel)))
                else:
                    metadata["entries_truncated"] = True
        except (OSError, reader.RequestError):
            metadata["scan_errors"] += 1
        finally:
            for fd in reversed(opened):
                try:
                    os.close(fd)
                except OSError:
                    metadata["scan_errors"] += 1
    if todo:
        metadata["entries_truncated"] = True
    metadata["eligible_candidates"] = len(candidates)
    return candidates, metadata


def _ordered_candidates(candidates: list[tuple[int, str, str]], research: bool):
    # Category quotas preserve source diversity: a large pile of utility
    # scripts cannot consume the entire budget for research notes, nor vice versa.
    if research:
        quotas = {"DOC": 24, "CODE": 10, "TEST": 6}
    else:
        quotas = {"CODE": 24, "TEST": 10, "DOC": 6}
    ranked = sorted(candidates, key=lambda x: (-x[0], x[1]))
    out = []
    seen = set()
    for category, maximum in quotas.items():
        chosen = 0
        for item in ranked:
            if item[2] == category and item[1] not in seen:
                seen.add(item[1])
                out.append(item)
                chosen += 1
                if chosen >= maximum:
                    break
    for item in ranked:
        if len(out) >= MAX_ATTEMPTED_FILES:
            break
        if item[1] not in seen:
            out.append(item)
            seen.add(item[1])
    return out


def discover_screened(
    root_fd: int,
    goal: str,
    reader,
) -> dict:
    """Return prioritized source texts screened by Revision 11 within its budget."""
    if not isinstance(goal, str) or not 0 < len(goal) <= 400:
        raise ValueError("INVALID_GOAL")
    candidates, meta = _candidate_paths(root_fd, goal, reader)
    read_budget = reader._ScanBudgetState()
    screened = []
    attempted = 0
    for score, rel, category in _ordered_candidates(candidates, meta["research_intent"]):
        if len(screened) >= MAX_SELECTED_FILES or attempted >= MAX_ATTEMPTED_FILES:
            break
        attempted += 1
        try:
            fd, validated = reader._open_validated_relative_file(root_fd, rel)
            try:
                text, digest, lines = reader._read_and_screen_fd(fd, validated, budget=read_budget)
            finally:
                os.close(fd)
        except reader.RequestError as exc:
            # Never emit the denied filename or any content from a rejected
            # file. Aggregate counts are sufficient to explain missing leads.
            if exc.code == "SECRET_CONTENT_DENIED":
                meta["screen_denied_count"] += 1
            else:
                meta["read_error_count"] += 1
            continue
        except OSError:
            meta["read_error_count"] += 1
            continue
        screened.append({
            "path": validated,
            "sha256": digest,
            "text": text,
            "lines": lines,
            "score": score,
            "kind": category,
        })
    remaining = max(0, len(candidates) - len(screened))
    if remaining or read_budget.any_truncated:
        meta["incomplete"] = True
    else:
        meta["incomplete"] = bool(meta["entries_truncated"] or meta["depth_truncated"]
                                   or meta["scan_errors"])
    meta.update({
        "source_attempts": attempted,
        "screened_sources": len(screened),
        "aggregate_source_bytes": read_budget.aggregate_bytes,
        "aggregate_budget_exhausted": read_budget.aggregate_bytes_truncated,
        "unselected_or_refused_candidates": remaining,
    })
    return {"files": screened, "selection": meta}
