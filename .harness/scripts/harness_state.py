#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Harness 执行状态的共享实现。

`.harness/dashboard/server.py` 与 `.harness/scripts/harness status` 都从这里取
状态，避免 CLI 与看板各维护一份 schema 校验和 lifecycle 推导。

只依赖 Python 标准库。直接运行时提供 CLI：

  python3 .harness/scripts/harness_state.py status [--json]
"""

import copy
import json
import os
import re
import subprocess
import sys
from datetime import date

# 仓库根默认 = 本模块所在 .harness/scripts 的上两级目录，可用 configure_root() 覆盖。
_SELF_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(_SELF_DIR))

# 这些随 ROOT 变化，由 configure_root() 设置。
CHANGES_DIR = ""
CURRENT_JSON = ""
CHECKPOINTS_DIR = ""
EVIDENCE_DIR = ""
FEATURE_INDEX = ""
DOCS_DIR = ""
# /api/doc 允许预览的目录前缀（绝对路径，norm 后）。
DOC_ALLOW = ()


def configure_root(root):
    global ROOT, CHANGES_DIR, CURRENT_JSON, CHECKPOINTS_DIR, EVIDENCE_DIR
    global FEATURE_INDEX, DOCS_DIR, DOC_ALLOW
    ROOT = os.path.abspath(root)
    CHANGES_DIR = os.path.join(ROOT, "openspec", "changes")
    CURRENT_JSON = os.path.join(ROOT, ".harness", "current.json")
    CHECKPOINTS_DIR = os.path.join(ROOT, ".harness", "checkpoints")
    EVIDENCE_DIR = os.path.join(ROOT, ".harness", "evidence")
    FEATURE_INDEX = os.path.join(ROOT, ".harness", "feature-index.json")
    DOCS_DIR = os.path.join(ROOT, "docs")
    DOC_ALLOW = tuple(os.path.normpath(p) for p in (
        CHANGES_DIR, CHECKPOINTS_DIR, EVIDENCE_DIR, DOCS_DIR, FEATURE_INDEX,
    ))


# 导入即以默认仓库根引导；调用方可再用 configure_root() 覆盖。
configure_root(ROOT)


TASK_RE = re.compile(r"^(\s*)-\s*\[([ xX])\]\s+(.*)$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
HUMAN_STATUSES = ("pending", "passed", "failed", "waived")
CURRENT_SCHEMA_VERSION = 2
LIFECYCLE_PHASES = (
    "planned",
    "implementing",
    "auto_verified",
    "awaiting_human",
    "awaiting_user_direction",
    "awaiting_human_and_user_direction",
    "ready_to_close",
    "blocked",
    "complete",
)
GATED_PHASES = {
    "planned",
    "auto_verified",
    "awaiting_human",
    "awaiting_user_direction",
    "awaiting_human_and_user_direction",
    "blocked",
}


# current.json 的唯一 schema 定义。两个平台脚本的 reset-current 都从这里生成，
# 不再各写一份字面量 JSON。
CURRENT_STATE_FIELDS = (
    "schema_version",
    "active_change",
    "candidate_changes",
    "change_context",
    "current_task",
    "last_verified_task",
    "working_files",
    "deleted_files",
    "blockers",
    "next_action",
    "dirty_assumptions",
    "last_checkpoint",
    "last_updated",
    "last_change_note",
    "verification_summary",
)

# 每个候选 change 的 context 只用这组结构化字段表达。
CONTEXT_FIELDS = (
    "summary",
    "phase",
    "blockers",
    "next_action",
    "depends_on",
    "last_checkpoint",
    "last_updated",
)

# summary 只说明"为什么它还没进 active"；细节属于 proposal.md / design.md。
CONTEXT_SUMMARY_MAX = 80


class StateConflict(ValueError):
    """The requested mutation conflicts with current durable state."""


class StateMigrationError(ValueError):
    """Legacy state cannot be migrated without losing information."""


# --------------------------------------------------------------------------
# 文件读写：保留编码与换行风格
# --------------------------------------------------------------------------

def read_text(path):
    with open(path, "rb") as fh:
        raw = fh.read()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    text = raw.decode("utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"
    return text, newline


def split_lines(text):
    return text.replace("\r\n", "\n").split("\n")


def write_lines(path, lines, newline):
    data = newline.join(lines).encode("utf-8")
    with open(path, "wb") as fh:
        fh.write(data)


def rel(path):
    """相对仓库根的 POSIX 风格路径，用于前端展示与 /api/doc。"""
    return os.path.relpath(path, ROOT).replace("\\", "/")


def first_heading(path):
    try:
        text, _ = read_text(path)
    except OSError:
        return None
    for line in split_lines(text):
        m = re.match(r"^#\s+(.*)$", line)
        if m:
            return m.group(1).strip()
    return None


# --------------------------------------------------------------------------
# 解析
# --------------------------------------------------------------------------

def parse_tasks(path):
    text, _ = read_text(path)
    lines = split_lines(text)
    items = []
    for idx, line in enumerate(lines):
        task_m = TASK_RE.match(line)
        if task_m:
            indent, mark, body = task_m.groups()
            items.append({
                "line": idx, "type": "task",
                "checked": mark.lower() == "x",
                "text": body.rstrip(), "indent": len(indent), "raw": line,
            })
            continue
        head_m = HEADING_RE.match(line)
        if head_m:
            hashes, title = head_m.groups()
            items.append({
                "line": idx, "type": "heading",
                "level": len(hashes), "text": title.rstrip(), "raw": line,
            })
    return items


def parse_human_checks(path):
    text, _ = read_text(path)
    lines = split_lines(text)
    rows = []
    header_idx = None
    for idx, line in enumerate(lines):
        if "状态" in line and "检查项" in line and line.strip().startswith("|"):
            header_idx = idx
            break
    if header_idx is None:
        return rows
    for idx in range(header_idx + 2, len(lines)):
        line = lines[idx]
        if not line.strip().startswith("|"):
            break
        cells = parse_table_row(line)
        if len(cells) < 5:
            continue
        rows.append({
            "line": idx, "status": cells[0], "item": cells[1],
            "operator": cells[2], "date": cells[3], "notes": cells[4], "raw": line,
        })
    return rows


def parse_table_row(line):
    parts = line.split("|")
    if parts and parts[0].strip() == "":
        parts = parts[1:]
    if parts and parts[-1].strip() == "":
        parts = parts[:-1]
    return [p.strip() for p in parts]


def build_table_row(status, item, operator, date, notes):
    return "| {} | {} | {} | {} | {} |".format(status, item, operator, date, notes)


# --------------------------------------------------------------------------
# 状态汇总
# --------------------------------------------------------------------------

def load_current():
    if not os.path.isfile(CURRENT_JSON):
        return {}
    text, _ = read_text(CURRENT_JSON)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        return {"_parse_error": str(exc)}


def save_current(current):
    text, newline = read_text(CURRENT_JSON) if os.path.isfile(CURRENT_JSON) else ("", "\n")
    _ = text  # 仅保留换行风格；JSON 统一格式化，避免手写状态漂移。
    current["last_updated"] = date.today().isoformat()
    data = json.dumps(current, ensure_ascii=False, indent=2)
    write_lines(CURRENT_JSON, split_lines(data), newline)


def require_change_exists(change_id):
    if not change_id or "/" in change_id or "\\" in change_id or change_id in (".", ".."):
        raise ValueError("非法 change id")
    change_dir = os.path.normpath(os.path.join(CHANGES_DIR, change_id))
    if os.path.commonpath([change_dir, CHANGES_DIR]) != os.path.normpath(CHANGES_DIR):
        raise ValueError("路径越界")
    if not os.path.isdir(change_dir):
        raise FileNotFoundError(change_dir)


CHANGE_MARKERS = (
    ".openspec.yaml",
    "proposal.md",
    "tasks.md",
    "quality-contract.md",
)


def is_discoverable_change_dir(change_dir):
    """Active change dirs must carry OpenSpec/harness metadata.

    Empty ghost directories can remain after a failed archive move on Windows;
    they must not appear on the kanban or participate in state normalization.
    """
    if not os.path.isdir(change_dir):
        return False
    return any(os.path.isfile(os.path.join(change_dir, name)) for name in CHANGE_MARKERS)


def existing_change_ids():
    if not os.path.isdir(CHANGES_DIR):
        return set()
    return {
        name for name in os.listdir(CHANGES_DIR)
        if name != "archive"
        and is_discoverable_change_dir(os.path.join(CHANGES_DIR, name))
    }


def _legacy_candidate(entry, valid_change_ids):
    """Return (canonical id, annotation) or (None, None)."""
    if not isinstance(entry, str):
        return None, None
    for change_id in sorted(valid_change_ids, key=len, reverse=True):
        if entry == change_id:
            return change_id, None
        prefix = change_id + " ("
        if entry.startswith(prefix) and entry.endswith(")"):
            return change_id, entry[len(prefix):-1]
    return None, None


def normalize_current_state(current, valid_change_ids):
    """Return a schema-v2 view without writing it.

    Legacy annotated candidates are accepted only when their prefix resolves to
    an existing change. Unknown entries are retained in the input object and
    reported as errors so any mutation can refuse data loss.
    """
    normalized = copy.deepcopy(current)
    warnings = []
    errors = []
    schema = current.get("schema_version", 1)
    if not isinstance(schema, int) or schema < 1 or schema > CURRENT_SCHEMA_VERSION:
        errors.append("Unsupported current.json schema_version: %r" % schema)

    raw_context = current.get("change_context") or {}
    if not isinstance(raw_context, dict):
        errors.append("change_context must be an object")
        raw_context = {}
    contexts = copy.deepcopy(raw_context)
    candidates = []
    seen = set()

    raw_candidates = current.get("candidate_changes") or []
    if not isinstance(raw_candidates, list):
        errors.append("candidate_changes must be an array")
        raw_candidates = []
    for entry in raw_candidates:
        change_id, annotation = _legacy_candidate(entry, valid_change_ids)
        if change_id is None:
            errors.append("Unresolved candidate entry: %r" % entry)
            continue
        if annotation is not None and schema >= CURRENT_SCHEMA_VERSION:
            errors.append("Schema v2 candidate is not canonical: %r" % entry)
            continue
        if annotation is not None:
            warnings.append("Legacy candidate %s will migrate to canonical schema v2." % change_id)
            context = contexts.setdefault(change_id, {})
            prior = context.get("summary")
            if prior and annotation != prior:
                context["summary"] = prior + "\n\nLegacy annotation: " + annotation
                warnings.append("Preserved existing context and legacy annotation for %s." % change_id)
            elif not prior:
                context["summary"] = annotation
        if change_id not in seen:
            candidates.append(change_id)
            seen.add(change_id)

    active = current.get("active_change")
    if active is not None and active not in valid_change_ids:
        errors.append("active_change does not resolve: %r" % active)
    if active in seen:
        warnings.append("Active change %s is also marked candidate." % active)

    for change_id, context in list(contexts.items()):
        if change_id not in valid_change_ids:
            errors.append("change_context key does not resolve: %r" % change_id)
        elif not isinstance(context, dict):
            errors.append("change_context[%s] must be an object" % change_id)

    normalized["schema_version"] = CURRENT_SCHEMA_VERSION
    normalized["candidate_changes"] = candidates
    normalized["change_context"] = contexts
    return {
        "state": normalized,
        "migration_pending": schema != CURRENT_SCHEMA_VERSION or bool(
            [w for w in warnings if w.startswith("Legacy candidate") or
             w.startswith("Preserved existing")]),
        "warnings": warnings,
        "errors": errors,
    }


def derive_lifecycle(change, context, is_active):
    """Project lifecycle without copying task/check outcomes into current.json."""
    context = context if isinstance(context, dict) else {}
    explicit = context.get("phase")
    warnings = []
    progress = change["task_progress"]
    counts = change["check_counts"]
    tasks_done = progress["total"] > 0 and progress["done"] == progress["total"]
    pending = counts.get("pending", 0)
    failed = counts.get("failed", 0)

    if explicit in LIFECYCLE_PHASES:
        phase = explicit
        source = "explicit"
    else:
        if explicit:
            warnings.append("Unknown explicit lifecycle phase %r; using derived phase." % explicit)
        source = "derived"
        if is_active:
            phase = "implementing"
        elif failed:
            phase = "blocked"
        elif tasks_done and pending:
            phase = "awaiting_human"
        elif tasks_done and change["has_checks"]:
            phase = "ready_to_close"
        elif tasks_done:
            phase = "complete"
        else:
            phase = "planned"

    if phase in ("ready_to_close", "complete") and (pending or failed):
        warnings.append("%s contradicts pending/failed human checks." % phase)
    if phase == "complete" and not tasks_done:
        warnings.append("complete contradicts incomplete tasks.")
    if phase == "ready_to_close" and not tasks_done:
        warnings.append("ready_to_close contradicts incomplete tasks.")
    if phase in ("awaiting_human", "awaiting_human_and_user_direction") and not (pending or failed):
        warnings.append("%s has no pending/failed human checks." % phase)
    if phase == "implementing" and not is_active:
        warnings.append("implementing change does not own the active slot.")

    return phase, source, warnings


def _context_from_top_level(current, change_id, phase):
    return {
        "phase": phase,
        "summary": (current.get("change_context") or {}).get(change_id, {}).get("summary"),
        "blockers": list(current.get("blockers") or []),
        "next_action": current.get("next_action"),
        "last_checkpoint": current.get("last_checkpoint"),
        "last_updated": current.get("last_updated") or date.today().isoformat(),
    }


def update_current_state(action, change_id=None):
    loaded = load_current()
    if loaded.get("_parse_error"):
        raise ValueError("current.json 解析失败: %s" % loaded["_parse_error"])
    result = normalize_current_state(loaded, existing_change_ids())
    if result["errors"]:
        raise StateMigrationError("; ".join(result["errors"]))
    current = result["state"]
    candidates = set(current.get("candidate_changes") or [])
    previous_active = current.get("active_change")
    contexts = current.setdefault("change_context", {})

    if action == "set-active":
        require_change_exists(change_id)
        if previous_active and previous_active != change_id:
            raise StateConflict(
                "active slot is owned by %s; release it before activating %s" %
                (previous_active, change_id))
        current["active_change"] = change_id
        candidates.discard(change_id)
        context = contexts.setdefault(change_id, {})
        context["phase"] = "implementing"
        context["last_updated"] = date.today().isoformat()
        if previous_active != change_id:
            current["current_task"] = (
                "继续执行 %s；读取 proposal.md、tasks.md、quality-contract.md 后推进 tasks。" %
                change_id)
            current["working_files"] = []
            current["blockers"] = list(context.get("blockers") or [])
            current["dirty_assumptions"] = []
            current["last_checkpoint"] = context.get("last_checkpoint")
            current["next_action"] = context.get("next_action") or current["current_task"]
    elif action == "clear-active":
        current["active_change"] = None
        if previous_active:
            change = build_change(previous_active)
            prior_context = contexts.get(previous_active) or {}
            phase, _source, _warnings = derive_lifecycle(change, prior_context, False)
            if phase == "implementing":
                phase, _source, _warnings = derive_lifecycle(change, {}, False)
            contexts[previous_active] = _context_from_top_level(
                current, previous_active, phase)
            if phase in GATED_PHASES:
                candidates.add(previous_active)
            verification_summary = current.get("verification_summary")
            if (isinstance(verification_summary, dict) and
                    verification_summary.get("active_change") == previous_active):
                verification_summary["active_change"] = None
        current["current_task"] = None
        current["working_files"] = []
    elif action == "add-candidate":
        require_change_exists(change_id)
        if change_id == previous_active:
            raise ValueError("active change 不需要候选标记")
        candidates.add(change_id)
    elif action == "remove-candidate":
        require_change_exists(change_id)
        candidates.discard(change_id)
    else:
        raise ValueError("未知 current 操作: %s" % action)

    current["candidate_changes"] = sorted(candidates)
    save_current(current)
    return current


def list_checkpoints(change_id):
    """返回该 change 的检查点相对路径列表，按文件名倒序（最新在前）。"""
    d = os.path.join(CHECKPOINTS_DIR, change_id)
    if not os.path.isdir(d):
        return []
    files = [f for f in os.listdir(d) if f.endswith(".md") and f != "README.md"]
    files.sort(reverse=True)
    return [rel(os.path.join(d, f)) for f in files]


def list_evidence(change_id):
    """返回该 change 的证据列表。

    同时覆盖两种布局：平铺的 `<change_id>*` 文件（历史约定），以及
    `.harness/evidence/<change_id>/` 子目录（当前约定，见 evidence/README.md）。
    """
    if not os.path.isdir(EVIDENCE_DIR):
        return []
    out = []
    for f in sorted(os.listdir(EVIDENCE_DIR)):
        if f == "README.md" or not f.startswith(change_id):
            continue
        full = os.path.join(EVIDENCE_DIR, f)
        if os.path.isfile(full):
            out.append({"path": rel(full), "size": os.path.getsize(full)})
        elif os.path.isdir(full):
            for cur, _dirs, files in os.walk(full):
                for name in sorted(files):
                    if name == "README.md":
                        continue
                    inner = os.path.join(cur, name)
                    out.append({"path": rel(inner), "size": os.path.getsize(inner)})
    return out


def build_change(name):
    change_dir = os.path.join(CHANGES_DIR, name)
    tasks_path = os.path.join(change_dir, "tasks.md")
    checks_path = os.path.join(change_dir, "human-checks.md")
    verif_path = os.path.join(change_dir, "verification.md")

    tasks = parse_tasks(tasks_path) if os.path.isfile(tasks_path) else None
    checks = parse_human_checks(checks_path) if os.path.isfile(checks_path) else None

    done = total = 0
    if tasks is not None:
        ti = [t for t in tasks if t["type"] == "task"]
        total = len(ti)
        done = sum(1 for t in ti if t["checked"])

    check_counts = {s: 0 for s in HUMAN_STATUSES}
    if checks:
        for r in checks:
            if r["status"] in check_counts:
                check_counts[r["status"]] += 1

    return {
        "id": name,
        "title": first_heading(os.path.join(change_dir, "proposal.md")) or name,
        "has_tasks": tasks is not None,
        "has_checks": checks is not None,
        "tasks": tasks,
        "human_checks": checks,
        "check_counts": check_counts,
        "task_progress": {"done": done, "total": total},
        "checkpoints": list_checkpoints(name),
        "verification": rel(verif_path) if os.path.isfile(verif_path) else None,
        "evidence": list_evidence(name),
        "has_proposal": os.path.isfile(os.path.join(change_dir, "proposal.md")),
        "has_design": os.path.isfile(os.path.join(change_dir, "design.md")),
    }


def build_library():
    """长期质量与知识文档清单（仅列存在的）。"""
    def docs_under(subdir, recursive=False):
        base = os.path.join(DOCS_DIR, subdir)
        out = []
        if not os.path.isdir(base):
            return out
        walker = os.walk(base) if recursive else [(base, [], os.listdir(base))]
        for cur, _dirs, files in walker:
            for f in sorted(files):
                if not f.endswith(".md"):
                    continue
                full = os.path.join(cur, f)
                out.append({"path": rel(full), "title": first_heading(full) or rel(full)})
        return out

    return {
        "quality": docs_under("quality"),
        "knowledge": docs_under("knowledge", recursive=True),
        "adr": docs_under("adr", recursive=True),
        "architecture": docs_under("architecture", recursive=True),
    }


def parse_feature_index():
    if not os.path.isfile(FEATURE_INDEX):
        return None
    text, _ = read_text(FEATURE_INDEX)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    feats = []
    for f in data.get("features", []):
        feats.append({
            "id": f.get("id"), "title": f.get("title"),
            "domain": f.get("domain"), "maturity": f.get("maturity"),
            "quality": f.get("quality"),
        })
    return {
        "project": data.get("project"),
        "last_updated": data.get("last_updated"),
        "features": feats,
        "path": rel(FEATURE_INDEX),
    }


def build_state():
    loaded = load_current()
    if loaded.get("_parse_error"):
        normalization = {
            "state": loaded,
            "migration_pending": False,
            "warnings": [],
            "errors": [loaded["_parse_error"]],
        }
    else:
        normalization = normalize_current_state(loaded, existing_change_ids())
    current = normalization["state"]
    active = current.get("active_change")
    candidates = set(current.get("candidate_changes") or [])
    contexts = current.get("change_context") or {}

    changes = []
    if os.path.isdir(CHANGES_DIR):
        for name in sorted(os.listdir(CHANGES_DIR)):
            change_dir = os.path.join(CHANGES_DIR, name)
            if not is_discoverable_change_dir(change_dir):
                continue
            c = build_change(name)
            c["is_active"] = name == active
            c["is_candidate"] = name in candidates
            context = contexts.get(name) if isinstance(contexts.get(name), dict) else {}
            phase, source, lifecycle_warnings = derive_lifecycle(
                c, context, c["is_active"])
            c["lifecycle_phase"] = phase
            c["phase_source"] = source
            c["lifecycle_warnings"] = lifecycle_warnings
            c["summary"] = context.get("summary")
            c["recovery"] = {
                "blockers": context.get("blockers") or [],
                "next_action": context.get("next_action"),
                "last_checkpoint": context.get("last_checkpoint"),
                "last_updated": context.get("last_updated"),
            }
            # Compatibility alias for older dashboard consumers. Execution and
            # membership are now exposed independently.
            c["status"] = phase
            changes.append(c)

    def sort_key(c):
        rank = {
            "implementing": 0,
            "blocked": 1,
            "awaiting_human": 1,
            "awaiting_human_and_user_direction": 1,
            "awaiting_user_direction": 2,
            "auto_verified": 3,
            "ready_to_close": 4,
            "planned": 5,
            "complete": 6,
        }.get(c["lifecycle_phase"], 9)
        return (0 if c["is_active"] else 1, rank, c["id"])
    changes.sort(key=sort_key)

    def queue_ids(*phases):
        return [c["id"] for c in changes if c["lifecycle_phase"] in phases]

    return {
        "current": {
            "schema_version": current.get("schema_version"),
            "active_change": active,
            "candidate_changes": sorted(candidates),
            "change_context": contexts,
            "current_task": current.get("current_task"),
            "last_verified_task": current.get("last_verified_task"),
            "blockers": current.get("blockers") or [],
            "next_action": current.get("next_action"),
            "working_files": current.get("working_files") or [],
            "dirty_assumptions": current.get("dirty_assumptions") or [],
            "last_checkpoint": current.get("last_checkpoint"),
            "session_wrap_up": current.get("session_wrap_up"),
            "last_updated": current.get("last_updated"),
            "parse_error": current.get("_parse_error"),
            "verification_summary": current.get("verification_summary"),
            "migration_pending": normalization["migration_pending"],
            "migration_warnings": normalization["warnings"],
            "state_errors": normalization["errors"],
        },
        "queues": {
            "active": [c["id"] for c in changes if c["is_active"]],
            "awaiting_human": queue_ids(
                "awaiting_human", "awaiting_human_and_user_direction"),
            "awaiting_user_direction": queue_ids(
                "awaiting_user_direction", "awaiting_human_and_user_direction"),
            "ready_to_close": queue_ids("ready_to_close"),
            "planned_candidates": [
                c["id"] for c in changes
                if c["is_candidate"] and c["lifecycle_phase"] == "planned"
            ],
        },
        "changes": changes,
        "library": build_library(),
        "feature_index": parse_feature_index(),
        "statuses": list(HUMAN_STATUSES),
        "root": ROOT,
    }


# --------------------------------------------------------------------------
# 写回
# --------------------------------------------------------------------------

def safe_change_path(change_id, filename):
    if not change_id or "/" in change_id or "\\" in change_id or change_id in (".", ".."):
        raise ValueError("非法 change id")
    path = os.path.normpath(os.path.join(CHANGES_DIR, change_id, filename))
    if os.path.commonpath([path, CHANGES_DIR]) != os.path.normpath(CHANGES_DIR):
        raise ValueError("路径越界")
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    return path


def toggle_task(change_id, line_no, checked, expected):
    path = safe_change_path(change_id, "tasks.md")
    text, newline = read_text(path)
    lines = split_lines(text)
    if line_no < 0 or line_no >= len(lines):
        raise IndexError("行号越界")
    if expected is not None and lines[line_no] != expected:
        return False, lines[line_no]
    m = TASK_RE.match(lines[line_no])
    if not m:
        raise ValueError("目标行不是任务复选框")
    indent, _mark, body = m.groups()
    lines[line_no] = "{}- [{}] {}".format(indent, "x" if checked else " ", body)
    write_lines(path, lines, newline)
    return True, lines[line_no]


def update_human_check(change_id, line_no, status, operator, date, notes, expected):
    if status not in HUMAN_STATUSES:
        raise ValueError("非法状态")
    path = safe_change_path(change_id, "human-checks.md")
    text, newline = read_text(path)
    lines = split_lines(text)
    if line_no < 0 or line_no >= len(lines):
        raise IndexError("行号越界")
    if expected is not None and lines[line_no] != expected:
        return False, lines[line_no]
    cells = parse_table_row(lines[line_no])
    if len(cells) < 5:
        raise ValueError("目标行不是合法的人工检查表格行")
    item = cells[1]
    lines[line_no] = build_table_row(status, item, operator, date, notes)
    write_lines(path, lines, newline)
    return True, lines[line_no]


def read_doc(relpath):
    """读取一个被白名单允许的文档，返回纯文本。"""
    if not relpath:
        raise ValueError("缺少 path")
    full = os.path.normpath(os.path.join(ROOT, relpath))
    if os.path.commonpath([full, ROOT]) != os.path.normpath(ROOT):
        raise ValueError("路径越界")
    allowed = False
    for prefix in DOC_ALLOW:
        if full == prefix:
            allowed = True
            break
        if os.path.isdir(prefix) and os.path.commonpath([full, prefix]) == prefix:
            allowed = True
            break
    if not allowed:
        raise ValueError("不在允许预览的目录内")
    if not os.path.isfile(full):
        raise FileNotFoundError(full)
    text, _ = read_text(full)
    return text


# --------------------------------------------------------------------------
# 状态 schema 与收尾
# --------------------------------------------------------------------------

def empty_current_state():
    """返回一个只含可恢复空执行槽的 current.json。"""
    return {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "active_change": None,
        "candidate_changes": [],
        "change_context": {},
        "current_task": None,
        "last_verified_task": None,
        "working_files": [],
        "deleted_files": [],
        "blockers": [],
        "next_action": None,
        "dirty_assumptions": [],
        "last_checkpoint": None,
        "last_updated": date.today().isoformat(),
        "last_change_note": None,
        "verification_summary": None,
    }


def reset_current_state():
    state = empty_current_state()
    save_current(state)
    return state


def audit_change_context(current):
    """检查 change_context 是否使用统一的结构化字段且摘要未超长。"""
    problems = []
    contexts = current.get("change_context") or {}
    if not isinstance(contexts, dict):
        return ["change_context 必须是对象"]

    for change_id in sorted(contexts):
        context = contexts[change_id]
        if not isinstance(context, dict):
            problems.append("%s: context 必须是对象" % change_id)
            continue
        unknown = sorted(set(context) - set(CONTEXT_FIELDS))
        if unknown:
            problems.append("%s: 未知 context 字段 %s" % (change_id, ", ".join(unknown)))
        missing = [f for f in ("summary", "phase", "next_action") if f not in context]
        if missing:
            problems.append("%s: 缺少字段 %s" % (change_id, ", ".join(missing)))
        summary = context.get("summary")
        if isinstance(summary, str) and len(summary) > CONTEXT_SUMMARY_MAX:
            problems.append(
                "%s: summary %d 字符，超过上限 %d；细节请写进 proposal.md/design.md"
                % (change_id, len(summary), CONTEXT_SUMMARY_MAX))
        phase = context.get("phase")
        if phase is not None and phase not in LIFECYCLE_PHASES:
            problems.append("%s: 未知 phase %r" % (change_id, phase))
        for field in ("blockers", "depends_on"):
            value = context.get(field)
            if value is not None and not isinstance(value, list):
                problems.append("%s: %s 必须是数组" % (change_id, field))
    return problems


def sync_candidates():
    """把候选集合重写为从 openspec/changes/ 派生的实际内容。

    active change 不占候选位；已有的 per-change context 原样保留。
    """
    loaded = load_current()
    if loaded.get("_parse_error"):
        raise ValueError("current.json 解析失败: %s" % loaded["_parse_error"])

    actual = existing_change_ids()
    active = loaded.get("active_change")
    derived = sorted(actual - ({active} if active else set()))
    before = list(loaded.get("candidate_changes") or [])
    loaded["candidate_changes"] = derived
    save_current(loaded)
    return {
        "before": before,
        "after": derived,
        "added": sorted(set(derived) - set(before)),
        "removed": sorted(set(before) - set(derived)),
    }


def finalize_close(change_id):
    """归档成功后让 current.json 与结果保持一致。

    摘除该 change 的候选与 context 条目；若它仍占着 active 执行槽则清空，
    并把指向它的 verification_summary.active_change 一并置空。
    """
    loaded = load_current()
    if loaded.get("_parse_error"):
        raise ValueError("current.json 解析失败: %s" % loaded["_parse_error"])

    removed = []
    candidates = [c for c in (loaded.get("candidate_changes") or [])
                  if c != change_id]
    if len(candidates) != len(loaded.get("candidate_changes") or []):
        removed.append("candidate_changes")
    loaded["candidate_changes"] = candidates

    contexts = loaded.get("change_context") or {}
    if isinstance(contexts, dict) and change_id in contexts:
        contexts.pop(change_id)
        removed.append("change_context")
    loaded["change_context"] = contexts

    released_active = False
    if loaded.get("active_change") == change_id:
        loaded["active_change"] = None
        loaded["current_task"] = None
        loaded["working_files"] = []
        released_active = True
        removed.append("active_change")

    summary = loaded.get("verification_summary")
    if isinstance(summary, dict) and summary.get("active_change") == change_id:
        summary["active_change"] = None
        removed.append("verification_summary.active_change")

    save_current(loaded)
    return {"change": change_id, "cleared": removed,
            "released_active": released_active}

# --------------------------------------------------------------------------
# 会话恢复摘要（harness status）
# --------------------------------------------------------------------------

def detect_drift(raw_current, changes):
    """比较 current.json 记录的成员关系与 openspec/changes/ 的实际内容。

    候选集合的权威来源是实际存在的非归档 change 目录；current.json 只提供
    per-change 的 override context。两者不一致时如实报告，不静默采用任一方。

    必须传入 **未经规范化** 的 current.json：`normalize_current_state()` 会剥掉
    无法解析的候选条目，规范化后的视图看不到指向已归档目录的陈旧条目。
    """
    actual = {c["id"] for c in changes}
    active = raw_current.get("active_change")

    recorded = set()
    for entry in raw_current.get("candidate_changes") or []:
        change_id, _annotation = _legacy_candidate(entry, actual)
        recorded.add(change_id if change_id else entry)

    contexts = set((raw_current.get("change_context") or {}).keys())

    tracked = recorded | ({active} if active else set())
    missing = sorted(actual - tracked)
    stale = sorted(tracked - actual)
    context_without_change = sorted(contexts - actual)
    change_without_context = sorted(actual - contexts)

    return {
        "missing_from_current": missing,
        "stale_in_current": stale,
        "context_without_change": context_without_change,
        "change_without_context": change_without_context,
        "clean": not (missing or stale or context_without_change),
    }


def recent_commits(count=5):
    try:
        proc = subprocess.run(
            ["git", "log", "--oneline", "-%d" % count],
            cwd=ROOT, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    return [line for line in proc.stdout.strip().split("\n") if line]


def build_status(commit_count=5):
    """一次给出恢复一轮会话所需的全部执行状态。"""
    state = build_state()
    current = state["current"]
    changes = state["changes"]
    # 漂移检测读原始 current.json：规范化视图已经丢弃了无法解析的条目。
    raw_current = load_current()
    drift = detect_drift(raw_current if not raw_current.get("_parse_error") else {},
                         changes)

    def entry(c):
        return {
            "id": c["id"],
            "phase": c["lifecycle_phase"],
            "phase_source": c["phase_source"],
            "tasks": "%d/%d" % (c["task_progress"]["done"], c["task_progress"]["total"]),
            "pending_checks": c["check_counts"].get("pending", 0),
            "failed_checks": c["check_counts"].get("failed", 0),
            "blockers": c["recovery"]["blockers"],
            "next_action": c["recovery"]["next_action"],
            "summary": c["summary"],
            "evidence_count": len(c["evidence"]),
            "warnings": c["lifecycle_warnings"],
        }

    active_id = current.get("active_change")
    return {
        "root": state["root"],
        "active_change": active_id,
        "active": next((entry(c) for c in changes if c["is_active"]), None),
        "current_task": current.get("current_task"),
        "blockers": current.get("blockers"),
        "next_action": current.get("next_action"),
        "working_files": current.get("working_files"),
        "dirty_assumptions": current.get("dirty_assumptions"),
        "last_checkpoint": current.get("last_checkpoint"),
        "last_updated": current.get("last_updated"),
        "candidates": [entry(c) for c in changes if not c["is_active"]],
        "queues": state["queues"],
        "drift": drift,
        "context_problems": audit_change_context(raw_current),
        "state_errors": current.get("state_errors") or [],
        "migration_pending": current.get("migration_pending"),
        "migration_warnings": current.get("migration_warnings") or [],
        "parse_error": current.get("parse_error"),
        "recent_commits": recent_commits(commit_count),
    }


def format_status(status):
    out = []
    add = out.append
    add("仓库根: %s" % status["root"])
    add("最后更新: %s" % (status["last_updated"] or "-"))
    add("")

    active = status["active"]
    if active:
        add("Active 执行槽: %s  [%s, tasks %s]" % (
            active["id"], active["phase"], active["tasks"]))
        if active["summary"]:
            add("  摘要: %s" % active["summary"])
        for b in active["blockers"] or []:
            add("  BLOCKER: %s" % b)
        if active["next_action"]:
            add("  下一步: %s" % active["next_action"])
        add("  证据: %d 份 | pending 人工检查: %d" % (
            active["evidence_count"], active["pending_checks"]))
    else:
        add("Active 执行槽: 空（进入实现前必须先选定唯一 active change）")
    if status["current_task"]:
        add("当前 task: %s" % status["current_task"])
    if status["next_action"] and not active:
        add("下一步: %s" % status["next_action"])
    add("")

    add("候选 change (%d):" % len(status["candidates"]))
    for c in status["candidates"]:
        flags = []
        if c["pending_checks"]:
            flags.append("human %d pending" % c["pending_checks"])
        if c["failed_checks"]:
            flags.append("human %d failed" % c["failed_checks"])
        if c["blockers"]:
            flags.append("%d blocker" % len(c["blockers"]))
        add("  %-52s %-28s tasks %-8s %s" % (
            c["id"], c["phase"], c["tasks"], ", ".join(flags)))
    add("")

    drift = status["drift"]
    if drift["clean"]:
        add("漂移检查: current.json 与 openspec/changes/ 一致")
    else:
        add("漂移检查: 不一致")
        for key, label in (
                ("missing_from_current", "实际存在但 current.json 未记录"),
                ("stale_in_current", "current.json 记录但目录不存在"),
                ("context_without_change", "change_context 指向不存在的 change")):
            if drift[key]:
                add("  %s: %s" % (label, ", ".join(drift[key])))
    if drift["change_without_context"]:
        add("  提示：以下 change 没有 context 条目: %s" %
            ", ".join(drift["change_without_context"]))

    for err in status["state_errors"]:
        add("状态错误: %s" % err)
    if status["parse_error"]:
        add("current.json 解析失败: %s" % status["parse_error"])
    if status["migration_pending"]:
        add("schema 迁移待写入: %s" % "; ".join(status["migration_warnings"]))

    if status["recent_commits"]:
        add("")
        add("最近提交:")
        for line in status["recent_commits"]:
            add("  %s" % line)

    return "\n".join(out)


USAGE = """用法:
  harness_state.py status [--json] [--root <path>]
  harness_state.py sync-candidates [--root <path>]
  harness_state.py finalize-close <change> [--root <path>]
  harness_state.py reset-current [--root <path>]
"""

COMMANDS = ("status", "sync-candidates", "finalize-close", "reset-current")


def main(argv):
    args = list(argv[1:])
    command = args.pop(0) if args and not args[0].startswith("-") else "status"

    as_json = False
    root = None
    positional = []
    unknown = []
    while args:
        arg = args.pop(0)
        if arg == "--json":
            as_json = True
        elif arg == "--root":
            root = args.pop(0) if args else None
            if root is None:
                unknown.append("--root 缺少路径")
        elif arg.startswith("--root="):
            root = arg.split("=", 1)[1]
        elif arg.startswith("-"):
            unknown.append(arg)
        else:
            positional.append(arg)

    if command not in COMMANDS or unknown:
        sys.stderr.write(USAGE)
        return 2
    if as_json and command != "status":
        sys.stderr.write("--json 只能与 status 一起使用\n")
        return 2
    if command == "finalize-close" and len(positional) != 1:
        sys.stderr.write("finalize-close 需要且只需要一个 <change>\n")
        return 2
    if command != "finalize-close" and positional:
        sys.stderr.write("%s 不接受位置参数: %s\n" % (command, " ".join(positional)))
        return 2

    if root:
        if not os.path.isdir(root):
            sys.stderr.write("错误: --root 不是目录: %s\n" % root)
            return 2
        configure_root(root)

    if command == "sync-candidates":
        result = sync_candidates()
        if result["added"] or result["removed"]:
            print("==> 候选集合已按 openspec/changes/ 重写")
            for change_id in result["added"]:
                print("    + %s" % change_id)
            for change_id in result["removed"]:
                print("    - %s" % change_id)
        else:
            print("==> 候选集合已与 openspec/changes/ 一致 (%d)" % len(result["after"]))
        return 0

    if command == "finalize-close":
        result = finalize_close(positional[0])
        if result["cleared"]:
            print("==> current.json 已收尾 %s：清理 %s" % (
                result["change"], ", ".join(result["cleared"])))
        else:
            print("==> current.json 无需收尾 %s" % result["change"])
        return 0

    if command == "reset-current":
        reset_current_state()
        print("==> 已清空 %s" % rel(CURRENT_JSON))
        return 0

    status = build_status()
    if as_json:
        print(json.dumps(status, ensure_ascii=False, indent=2))
    else:
        print(format_status(status))
        for problem in status["context_problems"]:
            print("context 问题: %s" % problem)

    # 漂移、状态错误与解析失败会让下一轮会话恢复到错误前提上，视为失败。
    if status["parse_error"] or status["state_errors"] or not status["drift"]["clean"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
