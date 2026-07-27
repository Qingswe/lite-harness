"""verify / close 门槛检查的回归测试。

重点覆盖旧实现被静默绕过的路径：空表格、状态列换位、非表格写法。
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

DASHBOARD_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = DASHBOARD_DIR.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import harness_checks  # noqa: E402

CHECK_SCRIPT = SCRIPTS_DIR / "harness_checks.py"

TABLE_HEADER = ("## 检查项\n\n"
                "| 状态 | 检查项 | 操作者 | 日期 | 证据或备注 |\n"
                "| --- | --- | --- | --- | --- |\n")


class ChecksTestCase(unittest.TestCase):
    def setUp(self):
        self._old_root = harness_checks.ROOT
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "openspec" / "changes").mkdir(parents=True)
        harness_checks.configure_root(str(self.root))

    def tearDown(self):
        harness_checks.configure_root(self._old_root)
        self.temp.cleanup()

    def write_checks(self, body, change_id="alpha"):
        change = self.root / "openspec" / "changes" / change_id
        change.mkdir(parents=True, exist_ok=True)
        (change / "human-checks.md").write_text("# Human Checks\n\n" + body,
                                                encoding="utf-8")
        return change_id


class HumanCheckGateTests(ChecksTestCase):
    def test_all_passed_rows_are_accepted(self):
        cid = self.write_checks(TABLE_HEADER +
                                "| passed | 目视确认 | 人 | 2026-07-26 | 截图 |\n")
        self.assertEqual(harness_checks.check_human_checks(cid), [])

    def test_empty_table_is_rejected(self):
        """旧实现只匹配 pending/failed 行，空表格会被静默放行。"""
        cid = self.write_checks(TABLE_HEADER + "\n## 失败记录\n\n- \n")
        problems = harness_checks.check_human_checks(cid)
        self.assertTrue(any("没有任何数据行" in p for p in problems), problems)

    def test_missing_table_is_rejected(self):
        """非表格写法（清单式）同样会被旧实现放行。"""
        cid = self.write_checks("## 检查项\n\n- [ ] 目视确认\n")
        problems = harness_checks.check_human_checks(cid)
        self.assertTrue(any("缺少规范的五列检查项表格" in p for p in problems), problems)

    def test_pending_row_is_rejected(self):
        cid = self.write_checks(TABLE_HEADER +
                                "| pending | 目视确认 |  |  |  |\n")
        problems = harness_checks.check_human_checks(cid)
        self.assertTrue(any("必须是 passed 或 waived" in p for p in problems), problems)

    def test_status_in_wrong_column_is_rejected(self):
        """状态列换位时，旧的首列正则匹配不到，会被误判为通过。"""
        cid = self.write_checks(TABLE_HEADER +
                                "| 目视确认 | pending | 人 | 2026-07-26 | - |\n")
        problems = harness_checks.check_human_checks(cid)
        self.assertTrue(problems)

    def test_waived_without_exemption_record_is_rejected(self):
        cid = self.write_checks(TABLE_HEADER +
                                "| waived | 不适用 | AI | 2026-07-26 | - |\n"
                                "\n## 豁免记录\n\n- \n")
        problems = harness_checks.check_human_checks(cid)
        self.assertTrue(any("豁免记录" in p for p in problems), problems)

    def test_waived_with_exemption_record_is_accepted(self):
        cid = self.write_checks(TABLE_HEADER +
                                "| waived | 不适用 | AI | 2026-07-26 | - |\n"
                                "\n## 豁免记录\n\n- 纯文档变更，契约不要求人工检查。\n")
        self.assertEqual(harness_checks.check_human_checks(cid), [])


class ProbeDecisionTests(ChecksTestCase):
    def write_contract(self, editmode, playmode, change_id="alpha"):
        change = self.root / "openspec" / "changes" / change_id
        change.mkdir(parents=True, exist_ok=True)
        (change / "quality-contract.md").write_text(
            "# Quality Contract\n\n## 必须验证\n\n"
            "- EditMode：%s\n- PlayMode：%s\n- 集成路径：无。\n\n## 回滚方式\n\n- 无\n"
            % (editmode, playmode), encoding="utf-8")
        return change_id

    def test_doc_only_contract_skips_probe(self):
        cid = self.write_contract("不需要；不改 Unity 代码。", "不要求；不改运行时行为。")
        needed, _reason = harness_checks.requires_unity_probe(cid)
        self.assertFalse(needed)

    def test_playmode_requirement_forces_probe(self):
        cid = self.write_contract(
            "无强制套件（纯映射修复）。",
            "Linux Editor 进入 Play Mode，确认无 `NotSupportedException`。")
        needed, _reason = harness_checks.requires_unity_probe(cid)
        self.assertTrue(needed, "『确认无 X』不应被当成不需要验证")

    def test_missing_contract_is_conservative(self):
        needed, reason = harness_checks.requires_unity_probe("never-existed")
        self.assertTrue(needed)
        self.assertIn("保守", reason)

    def test_empty_values_are_conservative(self):
        cid = self.write_contract("", "")
        needed, _reason = harness_checks.requires_unity_probe(cid)
        self.assertTrue(needed)


class DocReferenceTests(ChecksTestCase):
    def write_doc(self, text, name="CLAUDE.md"):
        (self.root / name).write_text(text, encoding="utf-8")

    def test_existing_path_passes(self):
        (self.root / "docs").mkdir()
        (self.root / "docs" / "quality").mkdir()
        (self.root / "docs" / "quality" / "README.md").write_text("x", encoding="utf-8")
        self.write_doc("见 `docs/quality/README.md`。\n")
        self.assertEqual(harness_checks.check_doc_references(), [])

    def test_missing_path_is_reported(self):
        (self.root / "openspec").mkdir(exist_ok=True)
        self.write_doc("归档在 `openspec/archive/`。\n")
        problems = harness_checks.check_doc_references()
        self.assertTrue(any("openspec/archive/" in p for p in problems), problems)

    def test_placeholder_and_relative_fragments_are_ignored(self):
        self.write_doc("看 `openspec/changes/<id>/proposal.md` 与 `specs/` 与 `tasks.md`。\n")
        self.assertEqual(harness_checks.check_doc_references(), [])

    def test_field_accessor_is_not_a_path(self):
        (self.root / ".harness").mkdir()
        (self.root / ".harness" / "current.json").write_text("{}", encoding="utf-8")
        self.write_doc("唯一执行槽是 `.harness/current.json.active_change`。\n")
        self.assertEqual(harness_checks.check_doc_references(), [])


class SkillConsistencyTests(ChecksTestCase):
    def write_skill(self, client, skill, content, filename="SKILL.md"):
        target = self.root / client / "skills" / skill / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def test_identical_copies_pass(self):
        for client in (".claude", ".cursor"):
            self.write_skill(client, "demo", "same body\n")
        self.assertEqual(harness_checks.check_skill_consistency(), [])

    def test_diverged_copies_are_reported(self):
        self.write_skill(".claude", "demo", "body A\n")
        self.write_skill(".cursor", "demo", "body B\n")
        problems = harness_checks.check_skill_consistency()
        self.assertTrue(any("demo" in p and "分叉" in p for p in problems), problems)

    def test_reference_files_are_compared_too(self):
        self.write_skill(".claude", "demo", "same\n")
        self.write_skill(".cursor", "demo", "same\n")
        self.write_skill(".claude", "demo", "ref A\n", "references/guide.md")
        self.write_skill(".cursor", "demo", "ref B\n", "references/guide.md")
        problems = harness_checks.check_skill_consistency()
        self.assertTrue(any("references/guide.md" in p for p in problems), problems)


class CheckCliTests(ChecksTestCase):
    def run_check(self, *args):
        return subprocess.run(
            [sys.executable, str(CHECK_SCRIPT), *args, "--root", str(self.root)],
            capture_output=True, text=True, timeout=60)

    def test_probe_needed_uses_exit_code(self):
        change = self.root / "openspec" / "changes" / "alpha"
        change.mkdir(parents=True)
        (change / "quality-contract.md").write_text(
            "# c\n\n## 必须验证\n\n- EditMode：不需要。\n- PlayMode：不需要。\n",
            encoding="utf-8")
        self.assertEqual(self.run_check("probe-needed", "alpha").returncode, 1)

    def test_unknown_command_is_usage_error(self):
        self.assertEqual(self.run_check("bogus").returncode, 2)

    def test_human_checks_requires_change_argument(self):
        self.assertEqual(self.run_check("human-checks").returncode, 2)


if __name__ == "__main__":
    unittest.main()
