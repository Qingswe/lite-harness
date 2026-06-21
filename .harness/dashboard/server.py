#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Harness 看板后端。

零依赖 Python stdlib HTTP 服务，集中展示并编辑：
- .harness/current.json                   执行状态（含 working_files / dirty_assumptions / session_wrap_up）
- openspec/changes/<id>/tasks.md          任务复选框（可编辑）
- openspec/changes/<id>/human-checks.md   人工检查表格（可编辑）

并只读预览：
- .harness/checkpoints/<id>/*.md          会话检查点
- openspec/changes/<id>/verification.md   验证记录
- .harness/evidence/<id>*                  验证证据
- docs/quality/*.md, docs/knowledge/**     长期质量与知识文档
- .harness/feature-index.json             能力索引

写回按行号 + 乐观锁，只改目标行，保留 UTF-8 无 BOM 编码与换行风格。
"""

import argparse
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# 仓库根默认 = 本脚本所在 .harness/dashboard 的上两级目录，可用 --root 覆盖。
WEB_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(WEB_DIR))

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


TASK_RE = re.compile(r"^(\s*)-\s*\[([ xX])\]\s+(.*)$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
HUMAN_STATUSES = ("pending", "passed", "failed", "waived")


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


def list_checkpoints(change_id):
    """返回该 change 的检查点相对路径列表，按文件名倒序（最新在前）。"""
    d = os.path.join(CHECKPOINTS_DIR, change_id)
    if not os.path.isdir(d):
        return []
    files = [f for f in os.listdir(d) if f.endswith(".md") and f != "README.md"]
    files.sort(reverse=True)
    return [rel(os.path.join(d, f)) for f in files]


def list_evidence(change_id):
    """返回文件名以 change_id 开头的证据相对路径列表。"""
    if not os.path.isdir(EVIDENCE_DIR):
        return []
    out = []
    for f in sorted(os.listdir(EVIDENCE_DIR)):
        if f == "README.md":
            continue
        if f.startswith(change_id):
            full = os.path.join(EVIDENCE_DIR, f)
            if os.path.isfile(full):
                out.append({"path": rel(full), "size": os.path.getsize(full)})
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
    current = load_current()
    active = current.get("active_change")
    candidates = set(current.get("candidate_changes") or [])

    changes = []
    if os.path.isdir(CHANGES_DIR):
        for name in sorted(os.listdir(CHANGES_DIR)):
            change_dir = os.path.join(CHANGES_DIR, name)
            if not os.path.isdir(change_dir) or name == "archive":
                continue
            c = build_change(name)
            c["is_active"] = name == active
            c["is_candidate"] = name in candidates
            changes.append(c)

    def sort_key(c):
        return (0 if c["is_active"] else (1 if c["is_candidate"] else 2), c["id"])
    changes.sort(key=sort_key)

    return {
        "current": {
            "active_change": active,
            "candidate_changes": sorted(candidates),
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
# HTTP
# --------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, content_type):
        with open(path, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            self._send_file(os.path.join(WEB_DIR, "index.html"), "text/html; charset=utf-8")
            return
        if parsed.path == "/api/state":
            try:
                self._send_json(build_state())
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": str(exc)}, 500)
            return
        if parsed.path == "/api/doc":
            qs = parse_qs(parsed.query)
            relpath = (qs.get("path") or [""])[0]
            try:
                content = read_doc(relpath)
                self._send_json({"path": relpath, "content": content})
            except ValueError as exc:
                self._send_json({"error": str(exc)}, 400)
            except FileNotFoundError:
                self._send_json({"error": "文件不存在"}, 404)
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": str(exc)}, 500)
            return
        self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        try:
            payload = self._read_body()
        except Exception as exc:  # noqa: BLE001
            self._send_json({"error": "请求体解析失败: %s" % exc}, 400)
            return
        try:
            if self.path == "/api/task":
                ok, line = toggle_task(payload["change"], int(payload["line"]),
                                       bool(payload["checked"]), payload.get("expected"))
                if not ok:
                    self._send_json({"error": "conflict", "current": line}, 409)
                    return
                self._send_json({"ok": True, "line": line})
                return
            if self.path == "/api/human-check":
                ok, line = update_human_check(
                    payload["change"], int(payload["line"]), payload["status"],
                    payload.get("operator", ""), payload.get("date", ""),
                    payload.get("notes", ""), payload.get("expected"))
                if not ok:
                    self._send_json({"error": "conflict", "current": line}, 409)
                    return
                self._send_json({"ok": True, "line": line})
                return
            self._send_json({"error": "not found"}, 404)
        except (KeyError, ValueError, IndexError) as exc:
            self._send_json({"error": str(exc)}, 400)
        except FileNotFoundError as exc:
            self._send_json({"error": "文件不存在: %s" % exc}, 404)
        except Exception as exc:  # noqa: BLE001
            self._send_json({"error": str(exc)}, 500)

    def log_message(self, fmt, *args):
        sys.stderr.write("[harness-dashboard] %s\n" % (fmt % args))


def main():
    parser = argparse.ArgumentParser(description="Harness 看板")
    parser.add_argument("--port", type=int, default=8777)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--root", default=ROOT,
                        help="仓库根目录（默认自动定位为 dashboard 上两级目录）")
    args = parser.parse_args()
    configure_root(args.root)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print("Harness dashboard started: http://{}:{}".format(args.host, args.port))
    print("Repo root: %s" % ROOT)
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.shutdown()


configure_root(ROOT)

if __name__ == "__main__":
    main()
