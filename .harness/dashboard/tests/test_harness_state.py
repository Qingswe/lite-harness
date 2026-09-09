"""共享状态模块与 `harness status` 的回归测试。

覆盖 dashboard 既有测试没有覆盖的部分：CLI 与看板共用同一实现、漂移检测、
证据子目录列举，以及 status 在状态不一致时以非零码退出。
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

DASHBOARD_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = DASHBOARD_DIR.parent / "scripts"
ROOT = DASHBOARD_DIR.parent.parent
for path in (str(DASHBOARD_DIR), str(SCRIPTS_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

import harness_state  # noqa: E402
import server  # noqa: E402

STATE_SCRIPT = SCRIPTS_DIR / "harness_state.py"


class SharedImplementationTests(unittest.TestCase):
    """server.py 必须复用状态层，而不是自带一份。"""

    def test_server_delegates_to_shared_module(self):
        for name in ("build_state", "derive_lifecycle",
                     "existing_change_ids"):
            self.assertIs(getattr(server, name), getattr(harness_state, name),
                          "%s 不是同一个实现" % name)

    def test_server_root_tracks_shared_module(self):
        self.assertEqual(server.ROOT, harness_state.ROOT)

    def test_server_defines_no_duplicate_state_logic(self):
        source = (DASHBOARD_DIR / "server.py").read_text(encoding="utf-8")
        for marker in ("def normalize_current_state", "def derive_lifecycle",
                       "def build_state", "def parse_verification_steps"):
            self.assertNotIn(marker, source, "server.py 仍自带 %s" % marker)

    def test_verification_record_has_one_parser(self):
        """verification.json 的解析只能有一处。

        历史上人工检查有两份解析器，两份都只读第一张表格，第二张表的行对状态
        计数与关闭门槛同时不可见。这条断言让那类分叉不可能再发生。
        """
        import harness_checks
        import harness_verification as hv
        # 三个消费方拿到的必须是同一个模块对象，不是各自导入的副本。
        for module in (harness_state, harness_checks):
            self.assertIs(module.hv, hv, "%s 应委派同一个解析模块" % module.__name__)
        self.assertIs(server.parse_verification_steps,
                      harness_state.parse_verification_steps)
        # 换根必须整条链一起换，否则两处会各看一个仓库。
        harness_checks.configure_root(str(DASHBOARD_DIR.parent.parent))
        self.assertEqual(hv.ROOT, harness_state.ROOT)
        self.assertEqual(hv.ROOT, harness_checks.ROOT)

    def test_both_platform_wrappers_expose_the_same_subcommands(self):
        """两平台子命令必须一致，否则同一个 change 在两台机器上结论不同。

        这条断言此前是**假的**：它遍历一份硬编码的子命令名单，逐个确认两边都
        提到过。名单里没有的子命令它看不见——只往 bash 加一个 `roles` 而忘了
        `harness.ps1`，测试照样通过。而这正是它唯一要防的那种错。

        现在从两个文件各自解析出实际的分发分支再比集合。名单不再需要维护，新增
        子命令时它自己就会发现另一边缺了什么。
        """
        bash_cmds = self.bash_subcommands()
        pwsh_cmds = self.pwsh_subcommands()
        # 先确认解析没有空转：解析不到任何分支时集合相等（空 == 空）会假绿。
        self.assertGreaterEqual(len(bash_cmds), 8,
                                "没能从 harness 解析出子命令：%s" % bash_cmds)
        self.assertGreaterEqual(len(pwsh_cmds), 8,
                                "没能从 harness.ps1 解析出子命令：%s" % pwsh_cmds)
        self.assertEqual(
            bash_cmds, pwsh_cmds,
            "两个 wrapper 的子命令集合不同：\n  只在 harness: %s\n  只在 harness.ps1: %s"
            % (sorted(bash_cmds - pwsh_cmds), sorted(pwsh_cmds - bash_cmds)))

    # 帮助与别名不是子命令，两边的写法本来就不同。
    WRAPPER_IGNORED = {"help", "--help", "-h", "*"}

    def bash_subcommands(self):
        """解析派发用的 `case` 分支标签。

        不按 `case ... in` 切块：文件里有两个 case 块，前一个是选项校验
        （`status|ready|next) ;;` 这种一行式），切错块会解析出空集。改成认分支
        标签本身的形状——独占一行、以 `)` 收尾——恰好只命中派发块。
        """
        text = (SCRIPTS_DIR / "harness").read_text(encoding="utf-8")
        found = set()
        for line in text.splitlines():
            m = re.match(r"^\s{2}([a-z][\w|-]*)\)\s*$", line)
            if m:
                found.update(m.group(1).split("|"))
        # 透传命令（check / roles）在 case 之前就被截走，它们的参数由各自的
        # Python 模块解析。漏掉这一类等于让整整一类子命令绕过一致性检查——
        # `check` 此前就是这样在 PowerShell 侧缺失了很久而没人发现。
        found.update(re.findall(r'^if \[ "\$command_name" = "([a-z][\w-]*)" \]',
                                text, re.M))
        return found - self.WRAPPER_IGNORED

    def pwsh_subcommands(self):
        """解析 `switch ($Command)` 里的分支标签。

        分支体可以另起一行也可以写在同一行（`"reset-current" { Reset-Current }`），
        两种都要认——只认前者会把后者报成「PowerShell 侧缺少这个子命令」。
        """
        text = (SCRIPTS_DIR / "harness.ps1").read_text(encoding="utf-8")
        body = text.split("switch ($Command)", 1)
        self.assertEqual(len(body), 2, "harness.ps1 里找不到子命令 switch 块")
        found = set(re.findall(r'^\s{4}"([a-z][\w-]*)"\s*\{', body[1], re.M))
        return found - self.WRAPPER_IGNORED


class TempRepoTestCase(unittest.TestCase):
    def setUp(self):
        self._old_root = harness_state.ROOT
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / ".harness" / "evidence").mkdir(parents=True)
        (self.root / "openspec" / "changes").mkdir(parents=True)
        harness_state.configure_root(str(self.root))

    def tearDown(self):
        harness_state.configure_root(self._old_root)
        self.temp.cleanup()

    def make_change(self, change_id, done=0, total=1):
        change = self.root / "openspec" / "changes" / change_id
        change.mkdir(parents=True, exist_ok=True)
        (change / "proposal.md").write_text("# %s\n" % change_id, encoding="utf-8")
        marks = ["- [x] done"] * done + ["- [ ] todo"] * (total - done)
        (change / "tasks.md").write_text("## 1\n\n" + "\n".join(marks) + "\n",
                                         encoding="utf-8")

    def write_current(self, **kwargs):
        payload = {"schema_version": 2, "active_change": None,
                   "candidate_changes": [], "change_context": {}}
        payload.update(kwargs)
        (self.root / ".harness" / "current.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")




class EvidenceListingTests(TempRepoTestCase):
    def test_lists_both_flat_files_and_change_subdirectory(self):
        self.make_change("alpha")
        evidence = self.root / ".harness" / "evidence"
        (evidence / "alpha-legacy-2026-01-01.json").write_text("{}", encoding="utf-8")
        (evidence / "alpha").mkdir()
        (evidence / "alpha" / "group1.json").write_text("{}", encoding="utf-8")
        (evidence / "alpha" / "README.md").write_text("skip", encoding="utf-8")
        (evidence / "unrelated.json").write_text("{}", encoding="utf-8")

        paths = [e["path"] for e in harness_state.list_evidence("alpha")]
        self.assertIn(".harness/evidence/alpha-legacy-2026-01-01.json", paths)
        self.assertIn(".harness/evidence/alpha/group1.json", paths)
        self.assertNotIn(".harness/evidence/alpha/README.md", paths)
        self.assertNotIn(".harness/evidence/unrelated.json", paths)


class StatusCliTests(TempRepoTestCase):
    def run_status(self, *args):
        return subprocess.run(
            [sys.executable, str(STATE_SCRIPT), "status",
             "--root", str(self.root), *args],
            capture_output=True, text=True, timeout=60)

    def test_json_output_is_parsable_and_matches_state(self):
        self.make_change("alpha", done=1, total=2)
        self.write_current(active_change="alpha")
        proc = self.run_status("--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertIsNone(payload["active_change"])
        self.assertEqual(payload["candidates"][0]["tasks"], "1/2")
        self.assertTrue(payload["drift"]["clean"])

    def test_all_changes_visible_without_registration(self):
        self.make_change("alpha")
        self.make_change("orphan")
        self.write_current(active_change="alpha")
        proc = self.run_status()
        self.assertEqual(proc.returncode, 0)
        self.assertIn("orphan", proc.stdout)

    def test_unknown_argument_is_rejected(self):
        proc = self.run_status("--bogus")
        self.assertEqual(proc.returncode, 2)

    def test_text_output_reports_empty_active_slot(self):
        self.make_change("alpha")
        self.write_current(candidate_changes=["alpha"])
        proc = self.run_status()
        self.assertIn("执行目标不持久化", proc.stdout)


if __name__ == "__main__":
    unittest.main()
