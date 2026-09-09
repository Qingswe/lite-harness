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
from datetime import date, datetime
from urllib.parse import unquote

# 仓库根默认 = 本模块所在 .harness/scripts 的上两级目录，可用 configure_root() 覆盖。
_SELF_DIR = os.path.dirname(os.path.abspath(__file__))
if _SELF_DIR not in sys.path:
    sys.path.insert(0, _SELF_DIR)

import harness_verification as hv  # noqa: E402

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
    # 验证记录的解析器必须跟着换根，否则两处会各看一个仓库。
    hv.configure_root(ROOT)


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
    "generated_by",
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


def parse_verification_steps(change_id):
    """读该 change 的验证步骤。解析委派 harness_verification，本文件不自带实现。

    返回 (steps, error)。error 非空表示记录无法解析——调用方 MUST 把它当作问题
    上报，MUST NOT 退化成"解析不到步骤所以没有未完成项"。
    """
    hv.configure_root(ROOT)
    try:
        data = hv.load_verification(change_id)
    except hv.VerificationFormatError as exc:
        return [], str(exc)

    steps = []
    for step in data["steps"]:
        steps.append({
            "id": step.get("id"),
            "role": str(step.get("role") or "").lower(),
            "status": str(step.get("status") or "").lower(),
            "rule": step.get("rule"),
            "tasks": step.get("tasks") or [],
            # `item` 是旧名字，前端表格还在用，保留。但 `how` / `pass_when` 必须
            # 按记录里的原名一起带出来：投影里改了名又丢了 `how`，
            # `hv.step_summary()` 就找不到任何字段，于是每个自动步骤都被摘要成
            # 「该步骤未写明要求」——记录里明明写了。
            "item": step.get("pass_when") or "",
            "how": step.get("how"),
            "pass_when": step.get("pass_when"),
            "fail_when": step.get("fail_when"),
            "needs_human_because": step.get("needs_human_because"),
            "observe": step.get("observe"),
            "migrated": bool(step.get("migrated")),
            "operator": step.get("operator"),
            "date": step.get("date"),
            "notes": step.get("note"),
            "evidence": step.get("evidence") or [],
        })
    return steps, None


def parse_table_row(line):
    parts = line.split("|")
    if parts and parts[0].strip() == "":
        parts = parts[1:]
    if parts and parts[-1].strip() == "":
        parts = parts[:-1]
    return [p.strip() for p in parts]


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
    "program.md",
    "verification.json",
    "quality-contract.md",  # 迁移前形态，保留以便旧 change 仍可被发现并报错。
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


# 只有这两个取值是"可归档"主张。其余 phase 描述的是进度或闸门，不构成主张，
# 人工写什么就采信什么——`planned` 与 `awaiting_human` 之间没有严格/宽松之分，
# 只有早晚之分，硬给它们排一个全序会把人工意图无谓地覆盖掉。
CLOSABLE_PHASES = ("ready_to_close", "complete")


def compute_readiness(change):
    """归档就绪度中由本模块拥有的判据。

    完整的七项判据还包括 strict 校验、质量文档预筛与角色隔离，它们由
    harness_checks 提供，在 harness 命令层合并。这里只算不需要外部进程的部分，
    并且**全部由计算得出**：人工写入的 phase 不参与。
    """
    blockers = []
    progress = change["task_progress"]
    tasks_done = progress["total"] > 0 and progress["done"] == progress["total"]
    if not tasks_done:
        blockers.append({
            "criterion": "tasks",
            "detail": "tasks.md 还有 %d 项未完成"
                      % (progress["total"] - progress["done"]),
            "owner": "ai",
        })

    if change.get("verification_error"):
        blockers.append({"criterion": "verification-record",
                         "detail": change["verification_error"],
                         "owner": "ai"})
        return {"ready": False, "blockers": blockers}

    hv.configure_root(ROOT)
    result = hv.verification_readiness(change["id"])
    blockers.extend(result["blockers"])
    return {"ready": not blockers, "blockers": blockers}


def derive_lifecycle(change, context, is_active):
    """Project lifecycle from computed readiness, not from declared phase."""
    context = context if isinstance(context, dict) else {}
    explicit = context.get("phase")
    warnings = []
    progress = change["task_progress"]
    counts = change["check_counts"]
    human_counts = change.get("human_counts") or {}
    tasks_done = progress["total"] > 0 and progress["done"] == progress["total"]
    pending = counts.get("pending", 0)
    failed = counts.get("failed", 0)
    human_pending = human_counts.get("pending", 0) + human_counts.get("failed", 0)

    readiness = compute_readiness(change)

    if is_active:
        derived = "implementing"
    elif failed:
        derived = "blocked"
    elif readiness["ready"]:
        derived = "ready_to_close"
    elif human_pending and tasks_done:
        derived = "awaiting_human"
    elif tasks_done:
        derived = "auto_verified"
    else:
        derived = "planned"

    phase = derived
    source = "derived"
    if explicit in LIFECYCLE_PHASES:
        if explicit in CLOSABLE_PHASES and not readiness["ready"]:
            # 人工声称可归档但计算判定未就绪：采信计算结果，并报告导致未就绪的
            # 具体判据。这是「只能收紧不能放宽」唯一真正生效的地方。
            reasons = "；".join(b["detail"] for b in readiness["blockers"][:3])
            warnings.append(
                "explicit phase %r claims closable but computed readiness is "
                "false; using computed %r. 阻塞判据：%s"
                % (explicit, derived, reasons or "无"))
        else:
            phase = explicit
            source = "explicit"
    elif explicit:
        warnings.append("Unknown explicit lifecycle phase %r; using derived phase." % explicit)

    if phase == "ready_to_close" and not readiness["ready"]:
        warnings.append("ready_to_close contradicts computed readiness.")
    if phase in ("ready_to_close", "complete") and (pending or failed):
        warnings.append("%s contradicts pending/failed verification steps." % phase)
    if phase == "complete" and not tasks_done:
        warnings.append("complete contradicts incomplete tasks.")
    if phase in ("awaiting_human", "awaiting_human_and_user_direction") and not human_pending:
        warnings.append("%s has no pending/failed human steps." % phase)
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


# 扩展名 → 证据类型。这张表必须是**全函数**：兜底走 `other-<ext>` 而不是
# `unclassified`。一个「未分类」筐会立刻装进所有不好归类的东西，然后按类型筛选
# 就永远漏——而 `other-xml` 仍然是一个确定的、可筛选的取值。
EVIDENCE_KINDS = {
    "image": (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp"),
    "test-result": (".json", ".xml"),
    "log": (".log", ".txt"),
    "doc": (".md",),
    "script": (".py", ".ps1", ".sh"),
}
_EXT_TO_KIND = {ext: kind
                for kind, exts in EVIDENCE_KINDS.items()
                for ext in exts}
IMAGE_EXTS = EVIDENCE_KINDS["image"]
# 历史上证据直接平铺在 .harness/evidence/ 下，没有 change 子目录。那批文件
# 可能仍然存在，必须有一个确定的 source 值，否则它们会从「按来源筛选」的
# 结果里整批消失。
LEGACY_SOURCE = "legacy-flat"
_DATE_IN_NAME = re.compile(r"(\d{4}-\d{2}-\d{2})")


def evidence_kind(path):
    """按扩展名给出证据类型。没见过的扩展名返回 other-<ext>，不返回空。"""
    ext = os.path.splitext(path)[1].lower()
    if ext in _EXT_TO_KIND:
        return _EXT_TO_KIND[ext]
    return "other-%s" % (ext.lstrip(".") or "none")


def evidence_date(full, name):
    """证据日期：优先取文件名里的 YYYY-MM-DD，取不到退回 mtime。

    不允许返回空——按月份筛选要能覆盖全集，缺一个就是一份证据从筛选里消失。
    """
    found = _DATE_IN_NAME.search(name)
    if found:
        return found.group(1)
    return datetime.fromtimestamp(os.path.getmtime(full)).strftime("%Y-%m-%d")


def _evidence_item(full, source):
    name = os.path.basename(full)
    stat = os.stat(full)
    return {
        "path": rel(full),
        "size": stat.st_size,
        "mtime": stat.st_mtime,
        "kind": evidence_kind(name),
        "source": source,
        "date": evidence_date(full, name),
    }


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
            out.append(_evidence_item(full, LEGACY_SOURCE))
        elif os.path.isdir(full):
            for cur, _dirs, files in os.walk(full):
                for name in sorted(files):
                    if name == "README.md":
                        continue
                    out.append(_evidence_item(os.path.join(cur, name), f))
    return out


def list_all_evidence():
    """全仓库的证据，含那些不属于任何现存 change 的。

    按 change 逐个调 list_evidence() 会漏掉已归档或已删除 change 留下的文件，
    而筛选选项要覆盖磁盘上真实存在的每一份证据，所以这里直接走目录。
    """
    if not os.path.isdir(EVIDENCE_DIR):
        return []
    out = []
    for entry in sorted(os.listdir(EVIDENCE_DIR)):
        if entry == "README.md":
            continue
        full = os.path.join(EVIDENCE_DIR, entry)
        if os.path.isfile(full):
            out.append(_evidence_item(full, LEGACY_SOURCE))
        elif os.path.isdir(full):
            for cur, _dirs, files in os.walk(full):
                for name in sorted(files):
                    if name == "README.md":
                        continue
                    out.append(_evidence_item(os.path.join(cur, name), entry))
    return out


def evidence_references():
    """路径 → 引用它的步骤 id 列表。

    反查方向是「证据被谁引用」，因为看板要在证据旁边显示它支撑哪一步；正向的
    「步骤引用了哪些证据」在 verification.json 里本来就有。

    两处刻意的选择：

    1. **走 `hv.load_verification()`，不自己 json.load。** 验证记录的解析只有
       `harness_verification` 一份实现，本文件不得自带第二份（有测试强制这条）。
       注意也不能用 `parse_verification_steps()`：那个投影不带 `evidence`，拿它
       反查会稳定地得到空表——而空表和「确实没人引用」长得一模一样。
    2. **连 archive/ 一起扫。** 证据的绝大多数引用来自已归档的 change（本仓库
       41 条引用里 33 条在 archive 下）。只扫活动 change 会让几乎每一份历史证据
       都显示成「无人引用」。
    """
    hv.configure_root(ROOT)
    refs = {}
    archive_dir = os.path.join(CHANGES_DIR, "archive")
    targets = []
    for name in sorted(existing_change_ids()):
        targets.append((name, name))
    if os.path.isdir(archive_dir):
        for name in sorted(os.listdir(archive_dir)):
            if os.path.isfile(os.path.join(archive_dir, name,
                                           "verification.json")):
                targets.append(("archive/" + name, name))
    for change_ref, label in targets:
        try:
            data = hv.load_verification(change_ref)
        except hv.VerificationFormatError:
            continue
        for step in data.get("steps") or []:
            for path in step.get("evidence") or []:
                refs.setdefault(path, []).append(
                    "%s/%s" % (label, step.get("id") or "?"))
    return refs


def build_evidence_index():
    """证据全集 + 三个筛选维度的取值分布。

    选项从数据算，不硬编码：硬编码的选项列表在新增一类证据之后不会自己长出来，
    那类证据就会同时不在任何选项里、也不在任何筛选结果里。
    """
    refs = evidence_references()
    items = list_all_evidence()
    for item in items:
        item["referenced_by"] = refs.get(item["path"], [])
    def tally(key):
        counts = {}
        for item in items:
            counts[item[key]] = counts.get(item[key], 0) + 1
        return [{"value": v, "count": counts[v]} for v in sorted(counts)]
    return {
        "items": items,
        "total": len(items),
        "kinds": tally("kind"),
        "sources": tally("source"),
        "months": [{"value": v, "count": c} for v, c in sorted(
            _month_counts(items).items())],
    }


def _month_counts(items):
    counts = {}
    for item in items:
        month = item["date"][:7]
        counts[month] = counts.get(month, 0) + 1
    return counts


def build_verification_flow(change_id, steps):
    """把验证过程投影成一张有向图：评估规则 → 步骤 → 结论。

    节点与边都从既有解析结果派生，不新写一份解析：规则来自
    `harness_verification.parse_program()`，步骤来自 `verification.json`，
    摘要复用 `hv.step_summary()`。

    每个步骤恰好产生一个节点——「流程图节点覆盖全部步骤」这条验收标准由构造
    保证，契约脚本再把它断言一遍。
    """
    nodes = []
    edges = []

    try:
        program = hv.parse_program(change_id)
    except Exception:  # noqa: BLE001  program.md 缺失或不可解析时只画步骤
        program = {"rules": {}, "rule_order": []}

    for rule_id in program["rule_order"]:
        nodes.append({
            "id": "rule:" + rule_id,
            "kind": "rule",
            "rank": 0,
            "label": rule_id,
            "detail": program["rules"].get(rule_id, ""),
            "status": None,
        })

    for step in steps:
        step_id = str(step.get("id"))
        role = str(step.get("role") or "").lower()
        nodes.append({
            "id": "step:" + step_id,
            "kind": "step",
            "rank": 1,
            "label": step_id,
            "detail": hv.step_summary(step),
            "status": str(step.get("status") or "pending").lower(),
            "role": role,
            "evidence": step.get("evidence") or [],
        })
        rule_id = str(step.get("rule") or "").strip()
        if rule_id:
            # 规则可能不在 program.md 里（lint 会报 unknown）。图上仍然画出来，
            # 否则这条步骤看起来凭空出现，而缺失恰恰是要让人看见的东西。
            if not any(n["id"] == "rule:" + rule_id for n in nodes):
                nodes.insert(0, {
                    "id": "rule:" + rule_id, "kind": "rule", "rank": 0,
                    "label": rule_id, "detail": "（program.md 里没有这条规则）",
                    "status": None,
                })
            edges.append({"from": "rule:" + rule_id, "to": "step:" + step_id,
                          "kind": "covers"})
        edges.append({"from": "step:" + step_id, "to": "conclusion",
                      "kind": "settles"})

    settled = sum(1 for s in steps
                  if str(s.get("status") or "").lower() in hv.TERMINAL_STATUSES)
    nodes.append({
        "id": "conclusion",
        "kind": "conclusion",
        "rank": 2,
        "label": "归档就绪",
        "detail": "%d / %d 步已有结论" % (settled, len(steps)),
        "status": "passed" if steps and settled == len(steps) else "pending",
    })

    return {
        "nodes": nodes,
        "edges": edges,
        "caption": "箭头从评估规则指向引用它的验证步骤，再从步骤指向归档结论："
                   "规则决定一步怎么算通过，全部步骤有结论后才谈得上归档。",
    }


def build_change(name):
    change_dir = os.path.join(CHANGES_DIR, name)
    tasks_path = os.path.join(change_dir, "tasks.md")
    verif_path = os.path.join(change_dir, "verification.json")
    program_path = os.path.join(change_dir, "program.md")

    tasks = parse_tasks(tasks_path) if os.path.isfile(tasks_path) else None
    steps, verif_error = parse_verification_steps(name)

    done = total = 0
    if tasks is not None:
        ti = [t for t in tasks if t["type"] == "task"]
        total = len(ti)
        done = sum(1 for t in ti if t["checked"])

    check_counts = {s: 0 for s in HUMAN_STATUSES}
    for step in steps:
        if step["status"] in check_counts:
            check_counts[step["status"]] += 1

    # 格式门槛在这里就跑（纯 Python，不起子进程），让 status 能提前提示，而不是
    # 等到 close 那一刻才暴露。完整门槛（strict、git、角色隔离）仍在 harness lint。
    lint_problems = [] if verif_error else hv.lint(name)

    human_steps = [s for s in steps if s["role"] == "human"]
    human_counts = {s: 0 for s in HUMAN_STATUSES}
    for step in human_steps:
        if step["status"] in human_counts:
            human_counts[step["status"]] += 1

    return {
        "id": name,
        "title": first_heading(os.path.join(change_dir, "proposal.md")) or name,
        "has_tasks": tasks is not None,
        # 记录无法解析时 has_checks 仍为 True：否则"解析不到步骤"会被当成
        # "没有未完成项"，那正是本轮要消灭的失效。
        "has_checks": bool(steps) or verif_error is not None,
        "tasks": tasks,
        "steps": steps,
        "human_steps": human_steps,
        "check_counts": check_counts,
        "human_counts": human_counts,
        "verification_error": verif_error,
        "verification_flow": build_verification_flow(name, steps),
        "lint_problems": lint_problems,
        "task_progress": {"done": done, "total": total},
        "checkpoints": list_checkpoints(name),
        "verification": rel(verif_path) if os.path.isfile(verif_path) else None,
        "program": rel(program_path) if os.path.isfile(program_path) else None,
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

    # 四个目录都递归。`quality` 曾经是非递归的，于是 docs/quality/pitfalls/ 下
    # 的三篇文档在看板里根本不存在——非递归的列举本身就是一处静默丢失。
    return {
        "quality": docs_under("quality", recursive=True),
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


# --------------------------------------------------------------------------
# 导航树
# --------------------------------------------------------------------------

# 每个 lifecycle phase 归到哪个二级分组。顺序即侧栏里的显示顺序。
NAV_PHASE_GROUPS = (
    ("implementing", "执行中", ("implementing",)),
    ("awaiting_human", "待人工检查",
     ("awaiting_human", "awaiting_human_and_user_direction")),
    ("awaiting_user_direction", "待用户指示", ("awaiting_user_direction",)),
    ("ready_to_close", "可关闭", ("auto_verified", "ready_to_close", "complete")),
    ("blocked", "受阻", ("blocked",)),
    ("planned", "已规划", ("planned",)),
)

# 知识与质量的二级分组。`docs/knowledge/` 有 46 篇，平铺在一层等于没有分层，
# 所以按子目录拆开；拆到二级为止，再深一层树就超过三层了。
NAV_LIBRARY_GROUPS = (
    ("quality", "质量文档", "quality", None),
    ("knowledge_changes", "知识库 · 变更笔记", "knowledge", "changes"),
    ("knowledge_pitfalls", "知识库 · 坑", "knowledge", "pitfalls"),
    ("knowledge_general", "知识库 · 综述", "knowledge", ""),
    ("adr", "架构决策 ADR", "adr", None),
    ("architecture", "架构", "architecture", None),
)

NAV_MAX_DEPTH = 3


def nav_node(key, label, kind, depth, children=None, count=None, **extra):
    """导航树的节点。

    `initial_expanded` 只对分组有意义，且规则是固定的：一级分组展开，二级分组
    收起。这样首屏能看到全部分组标题与计数（层级直接可识别），又不会把 46 篇
    知识文档同时铺开；任何叶子最多两次点击可达。
    """
    node = {
        "key": key,
        "label": label,
        "kind": kind,
        "depth": depth,
        "count": count,
        "initial_expanded": bool(children) and depth == 1,
        "children": children or [],
    }
    node.update(extra)
    return node


def _doc_group_children(library, source, subdir, depth):
    """把某个文档目录下的文档取出来，按需要限定到子目录。

    `subdir=""` 表示只要根目录下的，`None` 表示全部——两者不能混用，否则
    同一篇文档会同时落进两个分组，覆盖断言就会报重复。
    """
    out = []
    prefix = "docs/%s/" % source
    for doc in library.get(source) or []:
        rest = doc["path"][len(prefix):] if doc["path"].startswith(prefix) else ""
        top = rest.split("/")[0] if "/" in rest else ""
        if subdir is not None and top != subdir:
            continue
        out.append(nav_node(
            "doc:" + doc["path"], doc["title"], "doc", depth,
            doc_path=doc["path"]))
    return out


def build_nav_tree(changes, library, feature_index, evidence_by_change,
                   evidence_index=None):
    """从已经投影好的状态派生导航树。

    树建在服务端而不是前端，是为了让「任意目标两次点击可达」这条验收标准能在
    Python 里直接断言，不需要浏览器或 DOM 模拟。
    """
    tree = [nav_node("overview", "概览", "overview", 1)]

    change_groups = []
    for key, label, phases in NAV_PHASE_GROUPS:
        members = [c for c in changes if c["lifecycle_phase"] in phases]
        if not members:
            continue
        change_groups.append(nav_node(
            "changes/" + key, label, "group", 2, count=len(members),
            children=[nav_node(
                "change:" + c["id"], c["title"], "change", 3,
                change=c["id"],
                dot="active" if c["is_active"] else _phase_dot(c),
                progress=c["task_progress"]) for c in members]))
    if change_groups:
        tree.append(nav_node("changes", "变更", "group", 1, count=len(changes),
                             children=change_groups))

    library_groups = [nav_node(
        "library/system", "系统结构", "system", 2)]
    if feature_index and feature_index.get("features"):
        library_groups.append(nav_node(
            "library/feature_index", "能力索引", "feature_index", 2,
            count=len(feature_index["features"])))
    for key, label, source, subdir in NAV_LIBRARY_GROUPS:
        docs = _doc_group_children(library, source, subdir, 3)
        if docs:
            library_groups.append(nav_node(
                "library/" + key, label, "group", 2, count=len(docs),
                children=docs))
    if library_groups:
        tree.append(nav_node("library", "知识与质量", "group", 1,
                             count=sum(g["count"] or 0 for g in library_groups),
                             children=library_groups))

    # 「全部证据」是唯一能看到历史平铺那批文件的入口：它们不属于任何现存
    # change，按 change 分组的子节点永远列不到它们。
    total_evidence = len(evidence_index["items"]) if evidence_index else 0
    evidence_groups = [nav_node("evidence:*", "全部证据", "evidence", 2,
                                count=total_evidence, change=None)]
    for change_id in sorted(evidence_by_change):
        items = evidence_by_change[change_id]
        if items:
            evidence_groups.append(nav_node(
                "evidence:" + change_id, change_id, "evidence", 2,
                count=len(items), change=change_id))
    if total_evidence:
        tree.append(nav_node(
            "evidence", "证据", "group", 1, count=total_evidence,
            children=evidence_groups))

    return tree


def _phase_dot(change):
    return {
        "implementing": "active",
        "awaiting_human": "await",
        "awaiting_user_direction": "await",
        "awaiting_human_and_user_direction": "await",
        "auto_verified": "ready",
        "ready_to_close": "ready",
        "complete": "done",
        "blocked": "blocked",
    }.get(change["lifecycle_phase"], "cand")


def build_module_graph():
    """harness 脚本之间的依赖，从 import 语句派生。

    手绘的架构图会漂移，而漂移的图比没有图更糟——它让人对着一个不再成立的结构
    做决定。所以边集直接由 `ast` 解析出来，图和实现不可能对不上。
    """
    import ast

    sources = {}
    scripts_dir = os.path.join(ROOT, ".harness", "scripts")
    if os.path.isdir(scripts_dir):
        for name in sorted(os.listdir(scripts_dir)):
            if name.endswith(".py"):
                sources[name[:-3]] = os.path.join(scripts_dir, name)
    server_py = os.path.join(ROOT, ".harness", "dashboard", "server.py")
    if os.path.isfile(server_py):
        sources["server"] = server_py

    nodes = {}
    edges = []
    for module, path in sources.items():
        try:
            tree = ast.parse(read_text(path)[0])
        except (SyntaxError, OSError):
            continue
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        nodes[module] = {
            "id": module, "kind": "module", "label": module,
            "detail": rel(path), "rank": 0, "status": None,
        }
        for target in sorted(imported):
            if target in sources and target != module:
                edges.append({"from": module, "to": target, "kind": "imports"})

    # 被依赖得越多排得越靠右，读起来是「上层 → 底层」。
    incoming = {}
    for edge in edges:
        incoming[edge["to"]] = incoming.get(edge["to"], 0) + 1
    for module, node in nodes.items():
        node["rank"] = 1 if incoming.get(module) else 0
        node["detail"] = "%s · 被 %d 个模块依赖" % (
            node["detail"], incoming.get(module, 0))

    return {
        "nodes": sorted(nodes.values(), key=lambda n: (n["rank"], n["id"])),
        "edges": edges,
        "caption": "箭头从 A 指向 B 表示 A 直接 import 了 B，也就是 A 依赖 B 的"
                   "实现。右列是被依赖的底层模块。",
    }


def build_dependency_graph(changes, contexts):
    """change 之间的归档依赖，来自 change_context 里声明的 depends_on。"""
    nodes = []
    edges = []
    known = {c["id"] for c in changes}
    for change in changes:
        nodes.append({
            "id": change["id"], "kind": "change", "label": change["id"],
            "detail": "%s · 任务 %d/%d" % (
                change["lifecycle_phase"],
                change["task_progress"]["done"], change["task_progress"]["total"]),
            "rank": 0, "status": None,
        })
    for change in changes:
        context = contexts.get(change["id"])
        depends = (context or {}).get("depends_on") or [] \
            if isinstance(context, dict) else []
        for target in depends:
            if target in known:
                edges.append({"from": target, "to": change["id"],
                              "kind": "blocks"})
    for edge in edges:
        for node in nodes:
            if node["id"] == edge["to"]:
                node["rank"] = 1

    return {
        "nodes": nodes,
        "edges": edges,
        "caption": "箭头从 A 指向 B 表示 A 必须先归档，B 才能归档。没有箭头的 "
                   "change 之间没有归档顺序要求。",
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

    library = build_library()
    feature_index = parse_feature_index()
    evidence_by_change = {c["id"]: c["evidence"] for c in changes}
    evidence_index = build_evidence_index()

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
        "library": library,
        "feature_index": feature_index,
        "evidence_index": evidence_index,
        "nav_tree": build_nav_tree(changes, library, feature_index,
                                   evidence_by_change, evidence_index),
        "graphs": {
            "dependency": build_dependency_graph(changes, contexts),
            "modules": build_module_graph(),
        },
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


def _fallback_operator(change_id, step_id):
    """按步骤的 role 从角色档案取 operator。取不到就返回空，不猜。"""
    try:
        import harness_roles
        harness_roles.configure_root(ROOT)
        data = hv.load_verification(change_id)
        step = hv.find_step(data, step_id) or {}
        return harness_roles.resolve(step.get("role"))
    except Exception:  # noqa: BLE001
        # 角色档案坏了不该让写回失败——它只是个填表模板。
        return ""


def update_verification_step(change_id, step_id, status, operator, date_value,
                             notes, expected, evidence=None):
    """按 step id 寻址写入验证结论。

    id 寻址取代了旧的"行号 + 原始整行比对"乐观锁：行号会随文档编辑漂移，而
    id 天然稳定，冲突检测改为比较状态本身。
    """
    require_change_exists(change_id)
    hv.configure_root(ROOT)
    # 服务端兜底：operator 为空时按步骤的 role 从激活档案取。前端也会预填，但
    # 兜底必须在这里，否则「直接 POST {change, step, status}」就会写出一条没有
    # 操作者的结论。date 的兜底由 hv.set_step() 已有的 `or date.today()` 负责。
    #
    # 注意这里补的只是 operator（一个人名）。`evaluated_by` 从头到尾不经过这条
    # 路径——看板写不出非 human 的评估者身份，见 harness_roles.py 的模块说明。
    if not (operator or "").strip():
        operator = _fallback_operator(change_id, step_id) or operator
    try:
        hv.set_step(change_id, step_id, status, operator=operator,
                    date_value=date_value, note=notes, evidence=evidence,
                    expected_status=expected)
    except hv.StepConflict:
        data = hv.load_verification(change_id)
        step = hv.find_step(data, step_id)
        return False, (step or {}).get("status")
    return True, status


def _resolve_allowed(relpath, roots=None):
    """把相对路径解析成绝对路径，并确认它落在白名单内。

    读文件的入口有两个（文档预览与证据文件），它们必须共用这一份校验。写第二份
    等于给自己安排一次分叉，而分叉出来的那一份就是漏洞——两处只要有一处漏了
    「先解码再判定」或漏了 realpath，越界就成立。

    `roots` 为 None 时用 DOC_ALLOW；传入更窄的集合可以进一步收紧（证据端点只
    允许 EVIDENCE_DIR）。
    """
    if not relpath:
        raise ValueError("缺少 path")
    # 先解码：`%2e%2e%2f` 这类编码过的穿越如果不解码就判定，只会因为「文件不
    # 存在」而恰好失败，白名单本身并没有拦住它。
    relpath = unquote(relpath)
    if os.path.isabs(relpath):
        raise ValueError("只接受仓库内的相对路径")
    # realpath 而不是 normpath：normpath 只做字符串折叠，跟不进软链。证据目录
    # 里放一个指向 /etc 的软链，normpath 判定会通过。
    root_real = os.path.realpath(ROOT)
    full = os.path.realpath(os.path.join(ROOT, relpath))
    if full != root_real and os.path.commonpath([full, root_real]) != root_real:
        raise ValueError("路径越界")
    allowed = False
    for prefix in (roots if roots is not None else DOC_ALLOW):
        prefix = os.path.realpath(prefix)
        if full == prefix:
            allowed = True
            break
        if os.path.isdir(prefix) and \
                os.path.commonpath([full, prefix]) == prefix:
            allowed = True
            break
    if not allowed:
        raise ValueError("不在允许读取的目录内")
    if not os.path.isfile(full):
        raise FileNotFoundError(full)
    return full


def read_evidence_bytes(relpath):
    """读取一份证据的原始字节，返回 (bytes, 扩展名)。

    白名单比 read_doc 更窄：只有 .harness/evidence/ 下的文件。证据端点返回原始
    字节且带 Content-Type，把它的可读范围放宽到 DOC_ALLOW 等于让整个 docs/ 与
    openspec/ 都能被当作任意类型下载。
    """
    full = _resolve_allowed(relpath, roots=(EVIDENCE_DIR,))
    with open(full, "rb") as fh:
        return fh.read(), os.path.splitext(full)[1].lower()


def read_doc(relpath):
    """读取一个被白名单允许的文档，返回纯文本。

    路径校验委派 `_resolve_allowed()`——本文件只有那一处做越界判定。
    """
    text, _ = read_text(_resolve_allowed(relpath))
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

    # 已完成实现但已从 active 槽释放的 change 走的是另一条路径：它不在
    # active_change 上，所以上面那段不会执行，而 current_task / next_action
    # 仍然指着它。实测归档后 status 的「下一步」还在让人去复核一个已经不存在
    # 的 change——「下一个动作与实际不符」正是就绪度判据要消灭的东西。
    for field in ("current_task", "next_action"):
        value = loaded.get(field)
        if isinstance(value, str) and change_id in value:
            loaded[field] = None
            removed.append(field)

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
        human = c.get("human_counts") or {}
        return {
            "id": c["id"],
            "phase": c["lifecycle_phase"],
            "phase_source": c["phase_source"],
            "tasks": "%d/%d" % (c["task_progress"]["done"], c["task_progress"]["total"]),
            "pending_steps": c["check_counts"].get("pending", 0),
            "failed_steps": c["check_counts"].get("failed", 0),
            "pending_checks": human.get("pending", 0),
            "failed_checks": human.get("failed", 0),
            "verification_error": c.get("verification_error"),
            "lint_problems": len(c.get("lint_problems") or []),
            "lint_first": (c.get("lint_problems") or [None])[0],
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
        add("Active 执行槽: 空（日常协作无需执行槽；自动循环实现前须选定 active change）")
    if status["current_task"]:
        add("当前 task: %s" % status["current_task"])
    if status["next_action"] and not active:
        add("下一步: %s" % status["next_action"])
    add("")

    add("候选 change (%d):" % len(status["candidates"]))
    for c in status["candidates"]:
        flags = []
        # 记录无法解析时必须显式说出来：把它显示成"没有未完成项"正是本轮要
        # 消灭的失效（一个 224 字节的散文文档曾一直显示为零 pending）。
        if c.get("verification_error"):
            flags.append("验证记录不可解析")
        # 这里数的是 hv.lint 的记录格式问题，不是完整的关闭门槛——完整门槛要跑
        # git（角色隔离、归因），status 会从 0.05s 变成 12s，而 status 是每轮
        # 会话都跑的命令。所以标签只承诺它真的检查了的东西；门槛结论去
        # `harness ready` 或 `harness lint <id>` 看。
        if c.get("lint_problems"):
            flags.append("记录格式 %d 项待修" % c["lint_problems"])
        if c["pending_steps"]:
            flags.append("step %d pending" % c["pending_steps"])
        if c["failed_steps"]:
            flags.append("step %d failed" % c["failed_steps"])
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
