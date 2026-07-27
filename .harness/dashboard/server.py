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

状态解析、schema 校验、lifecycle 推导与写回逻辑都在
`.harness/scripts/harness_state.py`，与 `harness status` CLI 共用同一份实现；
本文件只负责 HTTP 层。
"""

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

WEB_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS_DIR = os.path.join(os.path.dirname(WEB_DIR), "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import harness_state  # noqa: E402
from harness_state import (  # noqa: E402
    StateConflict,
    StateMigrationError,
    build_state,
    configure_root,
    read_doc,
    toggle_task,
    update_current_state,
    update_human_check,
)


def __getattr__(name):
    """把未在本模块定义的名字委派给状态层。

    保持 `server.ROOT` / `server.normalize_current_state` 等既有调用方式可用，
    且取到的是状态层的实时值而不是导入时的快照。
    """
    return getattr(harness_state, name)


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
            if self.path == "/api/current":
                current = update_current_state(payload["action"], payload.get("change"))
                self._send_json({"ok": True, "current": current})
                return
            self._send_json({"error": "not found"}, 404)
        except (StateConflict, StateMigrationError) as exc:
            self._send_json({"error": str(exc)}, 409)
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
    parser.add_argument("--root", default=harness_state.ROOT,
                        help="仓库根目录（默认自动定位为 dashboard 上两级目录）")
    args = parser.parse_args()
    configure_root(args.root)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print("Harness dashboard started: http://{}:{}".format(args.host, args.port))
    print("Repo root: %s" % harness_state.ROOT)
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.shutdown()



if __name__ == "__main__":
    main()
