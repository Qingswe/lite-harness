#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Harness 看板后端。

零依赖 Python stdlib HTTP 服务，集中展示并编辑：
- openspec/changes/                     实时派生任务与验证状态
- openspec/changes/<id>/tasks.md          任务复选框（可编辑）
- /api/ready                              归档就绪度与阻塞归因（只读）
- openspec/changes/<id>/verification.json 验证步骤（可编辑，按 step id 寻址）

并只读预览：
- .harness/checkpoints/<id>/*.md          会话检查点
- openspec/changes/<id>/program.md        约束与评估规则
- .harness/evidence/<id>*                  验证证据
- docs/quality/*.md, docs/knowledge/**     长期质量与知识文档
- .harness/feature-index.json             能力索引

任务写回按行号 + 乐观锁；验证步骤按 step id 寻址，冲突以状态比对判定。

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

import harness_checks  # noqa: E402
import harness_roles  # noqa: E402
import harness_state  # noqa: E402
from harness_state import (  # noqa: E402
    StateConflict,
    StateMigrationError,
    build_state,
    configure_root,
    read_doc,
    toggle_task,
    update_verification_step,
)


def __getattr__(name):
    """把未在本模块定义的名字委派给状态层。

    保持 `server.ROOT` / `server.normalize_current_state` 等既有调用方式可用，
    且取到的是状态层的实时值而不是导入时的快照。
    """
    return getattr(harness_state, name)


# --------------------------------------------------------------------------
# 数据流声明
# --------------------------------------------------------------------------

# 每个 route 读写哪些文件。这是数据流图的唯一来源，也是唯一一份需要人写的
# 图数据——所以配一条防漂移断言：`check-dashboard-contract.py graphs` 会核对
# 已注册的 route 是否都在这里登记，新增 route 忘了登记就会失败。
# 「记得更新图」于是从纪律变成门槛。
DATA_FLOW = (
    {"route": "/api/state", "method": "GET",
     "reads": ["openspec/changes/",
               ".harness/feature-index.json", "docs/", ".harness/evidence/"],
     "writes": []},
    {"route": "/api/ready", "method": "GET",
     "reads": ["openspec/changes/"],
     "writes": []},
    {"route": "/api/doc", "method": "GET",
     "reads": ["openspec/changes/", ".harness/checkpoints/",
               ".harness/evidence/", "docs/", ".harness/feature-index.json"],
     "writes": []},
    {"route": "/api/evidence-file", "method": "GET",
     "reads": [".harness/evidence/"],
     "writes": []},
    {"route": "/api/roles", "method": "GET",
     "reads": [".harness/roles.json"],
     "writes": [".harness/roles.json"]},
    {"route": "/api/task", "method": "POST",
     "reads": ["openspec/changes/"],
     "writes": ["openspec/changes/"]},
    {"route": "/api/verification-step", "method": "POST",
     "reads": ["openspec/changes/"],
     "writes": ["openspec/changes/"]},
)


def data_flow_graph():
    """把 DATA_FLOW 投影成一张有向图：文件 → route → 文件。"""
    nodes = {}
    edges = []

    def add(node_id, kind, label, detail, rank):
        nodes.setdefault(node_id, {
            "id": node_id, "kind": kind, "label": label,
            "detail": detail, "rank": rank, "status": None})

    for entry in DATA_FLOW:
        route_id = "route:" + entry["route"]
        add(route_id, "route", entry["route"],
            entry["method"] + " 端点", 1)
        for path in entry["reads"]:
            add("file:" + path, "file", path, "仓库里的文件或目录", 0)
            edges.append({"from": "file:" + path, "to": route_id,
                          "kind": "reads"})
        for path in entry["writes"]:
            add("sink:" + path, "file", path, "被写回的文件", 2)
            edges.append({"from": route_id, "to": "sink:" + path,
                          "kind": "writes"})

    return {
        "nodes": sorted(nodes.values(), key=lambda n: (n["rank"], n["id"])),
        "edges": edges,
        "caption": "箭头从文件指向端点表示该端点读它；从端点指向文件表示该端点"
                   "写它。左列是数据来源，右列是会被改动的文件。",
    }


def registered_routes():
    """从 do_GET / do_POST 的源码里取出实际注册的 route。

    从源码取而不是维护第二份清单：两份清单会分叉，而分叉的那一刻正是防漂移
    断言应该报警的时刻。
    """
    import inspect
    import re as _re
    found = set()
    for handler in (Handler.do_GET, Handler.do_POST):
        source = inspect.getsource(handler)
        found.update(_re.findall(r'["\'](/api/[\w-]+)["\']', source))
    return found


# --------------------------------------------------------------------------
# 静态资源
# --------------------------------------------------------------------------

# 前端拆成了多个文件，需要一条静态路由。它的白名单**比 /api/doc 更窄**：只认
# WEB_DIR 下不含路径分隔符的这两种扩展名。刻意不复用 DOC_ALLOW——那份白名单
# 服务于文档预览，把它扩到能读脚本目录等于把 .harness/scripts/ 也变成可下载。
STATIC_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
}

# 证据文件按扩展名映射 Content-Type。没登记的扩展名一律按 octet-stream 下发，
# 不猜——猜错的那次就是让浏览器把一个 .log 当 text/html 解析。
EVIDENCE_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
    ".json": "application/json; charset=utf-8",
    ".xml": "application/xml; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".log": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
}


def resolve_static(path):
    """把 URL 路径解析为 WEB_DIR 下的静态文件，非法则返回 None。"""
    from urllib.parse import unquote
    # 先解码再校验：否则 %2e%2e%2f 这种编码过的穿越只会因为「文件不存在」而
    # 恰好失败，白名单本身并没有拦住它。
    name = unquote(path).lstrip("/")
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return None
    ext = os.path.splitext(name)[1].lower()
    if ext not in STATIC_TYPES:
        return None
    full = os.path.join(WEB_DIR, name)
    if not os.path.isfile(full):
        return None
    return full, STATIC_TYPES[ext]


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

    def _send_bytes(self, body, content_type):
        """下发原始字节。

        两个安全头是承重的，不是装饰：
        - nosniff 阻止浏览器忽略 Content-Type 去猜内容类型；
        - CSP default-src 'none' 保证即便某份证据真的被当成文档解析，它也拿不到
          任何外部能力。证据是脚本写出来的，而脚本的输入未必都是自己产的。
        """
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'")
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
        static = resolve_static(parsed.path)
        if static:
            self._send_file(*static)
            return
        if parsed.path == "/api/ready":
            try:
                # 与 harness ready 共用同一份实现；看板不新建第二份就绪度推导。
                # run_strict=False：每个 change 起一次 openspec 子进程对交互式
                # 看板太慢，strict 仍由 harness lint / close 把关。
                harness_checks.configure_root(harness_state.ROOT)
                self._send_json(harness_checks.build_ready_report(
                    run_strict=False))
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": str(exc)}, 500)
            return
        if parsed.path == "/api/state":
            try:
                state = build_state()
                # 数据流图的来源在 HTTP 层，所以在这里并进状态投影，而不是让
                # 状态层去猜有哪些 route。
                state["graphs"]["data_flow"] = data_flow_graph()
                # 角色档案随状态一起下发：前端每渲染一个步骤行都要用它预填
                # operator，单开一次请求只是多一个可失败的时点。
                harness_roles.configure_root(harness_state.ROOT)
                try:
                    state["roles"] = harness_roles.load()
                except harness_roles.RoleError as exc:
                    # 档案坏了不该让整个看板打不开——它只是填表模板。
                    state["roles"] = {"error": str(exc), "profiles": []}
                self._send_json(state)
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": str(exc)}, 500)
            return
        if parsed.path == "/api/evidence-file":
            qs = parse_qs(parsed.query)
            relpath = (qs.get("path") or [""])[0]
            try:
                body, ext = harness_state.read_evidence_bytes(relpath)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            except FileNotFoundError:
                self._send_json({"error": "文件不存在"}, 404)
                return
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": str(exc)}, 500)
                return
            self._send_bytes(body, EVIDENCE_TYPES.get(
                ext, "application/octet-stream"))
            return
        if parsed.path == "/api/roles":
            try:
                harness_roles.configure_root(harness_state.ROOT)
                self._send_json(harness_roles.load())
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
            if self.path == "/api/verification-step":
                ok, current = update_verification_step(
                    payload["change"], payload["step"], payload["status"],
                    payload.get("operator", ""), payload.get("date", ""),
                    payload.get("notes", ""), payload.get("expected"),
                    payload.get("evidence"))
                if not ok:
                    self._send_json({"error": "conflict", "current": current}, 409)
                    return
                self._send_json({"ok": True, "status": current})
                return
            if self.path == "/api/roles":
                # 只允许切换激活档案。这里刻意不提供「任意写入档案」的入口：
                # 档案编辑走 `harness roles set`，看板只做选择。
                harness_roles.configure_root(harness_state.ROOT)
                if payload.get("action") != "use":
                    self._send_json({"error": "只支持 action=use"}, 400)
                    return
                try:
                    state = harness_roles.use(payload.get("profile"))
                except harness_roles.RoleError as exc:
                    self._send_json({"error": str(exc)}, 400)
                    return
                self._send_json({"ok": True, "roles": state})
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
