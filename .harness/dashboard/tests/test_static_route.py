"""静态路由的边界用例。

前端拆成 index.html / theme.css / app.js / graph.js 后需要一条静态路由。它是
本仓库里少数几个直接把磁盘文件交出去的入口之一，所以边界要显式钉住：只认
WEB_DIR 下不含路径分隔符的 .css / .js，不复用也不放宽 /api/doc 的白名单。
"""

import os
import re
import sys
import unittest
from pathlib import Path


DASHBOARD_DIR = Path(__file__).resolve().parents[1]
if str(DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_DIR))

import server  # noqa: E402


class StaticRouteTests(unittest.TestCase):
    def test_allowed_assets_resolve_with_correct_type(self):
        for name, expected in (
                ("/theme.css", "text/css; charset=utf-8"),
                ("/app.js", "text/javascript; charset=utf-8"),
                ("/graph.js", "text/javascript; charset=utf-8")):
            with self.subTest(name=name):
                resolved = server.resolve_static(name)
                self.assertIsNotNone(resolved, "%s 应该可服务" % name)
                full, content_type = resolved
                self.assertEqual(expected, content_type)
                self.assertEqual(
                    os.path.dirname(os.path.abspath(full)), server.WEB_DIR)

    def test_traversal_and_separators_are_rejected(self):
        for name in (
                "/../scripts/harness_state.py",
                "/..%2fscripts%2fharness_state.py",
                "%2e%2e%2fscripts%2fharness_state.py",
                "/sub/dir/app.js",
                "/sub\\dir\\app.js",
                "/.hidden.css"):
            with self.subTest(name=name):
                self.assertIsNone(server.resolve_static(name))

    def test_non_whitelisted_extensions_are_rejected(self):
        # index.html 走它自己的分支；其余扩展名一律不经静态路由外泄。
        for name in ("/server.py", "/README.md", "/index.html",
                     "/UPDATER-PARITY.md", "/theme.css.bak", "/app"):
            with self.subTest(name=name):
                self.assertIsNone(server.resolve_static(name))

    def test_missing_file_is_rejected_without_touching_disk_outside_web_dir(self):
        self.assertIsNone(server.resolve_static("/does-not-exist.css"))


class FrontendAssetTests(unittest.TestCase):
    """零依赖是 README 里的承重属性，用断言而不是措辞守住它。"""

    ASSETS = ("index.html", "theme.css", "app.js", "graph.js")

    # 只找真正会发起网络请求的写法。SVG 的命名空间 URI
    # （http://www.w3.org/2000/svg）长得像 URL 但从不被请求，把它算成外部依赖
    # 会让这条断言开始误报，而误报的断言很快就会被人关掉。
    FETCHING = (
        re.compile(r"""\b(?:src|href)\s*=\s*["']https?://""", re.I),
        re.compile(r"""url\(\s*["']?https?://""", re.I),
        re.compile(r"""\b(?:import|require)\b[^\n]*["']https?://""", re.I),
        re.compile(r"""["']//(?:cdn|unpkg|jsdelivr)""", re.I),
    )

    def test_no_external_resource_references(self):
        for name in self.ASSETS:
            text = (DASHBOARD_DIR / name).read_text(encoding="utf-8")
            with self.subTest(name=name):
                for pattern in self.FETCHING:
                    match = pattern.search(text)
                    if match:
                        self.fail("%s 引用了外部资源: %s"
                                  % (name, match.group(0)))


if __name__ == "__main__":
    unittest.main()
