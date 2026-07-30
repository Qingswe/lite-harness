"""verify / close 门槛检查的回归测试。

重点覆盖旧实现被静默绕过的路径：空记录、非规范写法、未迁移形态。旧版本这些
断言是针对五列表格写的；表格形态已被 verification.json 取代，断言的**语义**
逐条保留下来（空不得通过、非终态不得通过、非规范格式不得静默放行、豁免必须
有记录），只是承载形式换了。
"""

import json
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

PROGRAM = """# Program — alpha

## 风险等级

- 等级：`low`

## 评估规则

| id | 规则 | 通过依据 |
| --- | --- | --- |
| `R1` | 目视确认 | 见步骤 |

## 必须验证

- 单元测试：跑 harness 回归套件。

## 不验证及理由

- EditMode：不执行，不触及 Unity。

## 可观测性与回滚

- 日志：脚本 stderr。
- 回滚方式：git revert。
"""


def step(**overrides):
    base = {
        "id": "H1", "role": "human", "tasks": [], "rule": "R1",
        # 刻意不提 Unity：探针判定会扫描步骤文本，默认夹带会污染无关用例。
        "observe": "打开 docs/quality/scorecard.md 的「战斗」评分行",
        "pass_when": "评分行的列数与表头一致且引用了验证证据",
        "fail_when": "出现列数错位，或评分变化没有对应的证据引用",
        "needs_human_because": "需要产品判断，AI 无法为评分合理性产出证据",
        "status": "passed", "operator": "人", "date": "2026-07-26",
        "evaluated_by": {"agent": "human", "model": "human"},
        "evidence": [".harness/evidence/alpha/shot.png"], "note": None,
    }
    base.update(overrides)
    return base


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

    def write_record(self, steps, change_id="alpha", program=PROGRAM,
                     evidence=True):
        change = self.root / "openspec" / "changes" / change_id
        change.mkdir(parents=True, exist_ok=True)
        if program is not None:
            (change / "program.md").write_text(program, encoding="utf-8")
        record = {
            "schema_version": 1, "change": change_id, "baseline_commit": "abc1234",
            "environment": {"os": "Linux", "unity": None, "date": "2026-07-26"},
            "steps": steps, "uncovered": [],
            "quality_docs": {"prescreen_run": "2026-07-26", "triggered": []},
            "conclusion": {"status": "passed", "note": "ok"},
        }
        (change / "verification.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        if evidence:
            target = self.root / ".harness" / "evidence" / change_id / "shot.png"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("x", encoding="utf-8")
        return change_id

    def write_legacy(self, body, change_id="alpha"):
        change = self.root / "openspec" / "changes" / change_id
        change.mkdir(parents=True, exist_ok=True)
        (change / "human-checks.md").write_text("# Human Checks\n\n" + body,
                                                encoding="utf-8")
        return change_id


class VerificationGateTests(ChecksTestCase):
    def test_all_terminal_steps_are_accepted(self):
        cid = self.write_record([step()])
        self.assertEqual(harness_checks.check_verification(cid), [])

    def test_empty_record_is_rejected(self):
        """旧实现只匹配 pending/failed 行，空表格会被静默放行。"""
        cid = self.write_record([])
        problems = harness_checks.check_verification(cid)
        self.assertTrue(any("没有任何步骤" in p for p in problems), problems)

    def test_legacy_format_is_rejected(self):
        """非规范写法（迁移前的表格文档）不得被静默放行。"""
        cid = self.write_legacy("## 检查项\n\n- [ ] 目视确认\n")
        problems = harness_checks.check_verification(cid)
        self.assertTrue(any("迁移前形态" in p for p in problems), problems)

    def test_pending_step_is_rejected(self):
        cid = self.write_record([step(status="pending", operator=None,
                                      date=None, evaluated_by=None,
                                      evidence=[])])
        problems = harness_checks.check_verification(cid)
        self.assertTrue(any("必须是 passed 或 waived" in p for p in problems),
                        problems)

    def test_invalid_status_value_is_rejected(self):
        """旧格式里状态列换位会被误判为通过；新格式中非法取值必须报错。"""
        cid = self.write_record([step(status="目视确认")])
        self.assertTrue(harness_checks.check_verification(cid))

    def test_waived_without_note_is_rejected(self):
        cid = self.write_record([step(status="waived", note="")])
        problems = harness_checks.check_verification(cid)
        self.assertTrue(any("豁免说明" in p for p in problems), problems)

    def test_waived_with_note_is_accepted(self):
        cid = self.write_record([step(status="waived",
                                      note="纯文档变更，不要求人工检查。")])
        self.assertEqual(harness_checks.check_verification(cid), [])


class ProbeDecisionTests(ChecksTestCase):
    def write_program(self, skip_line, steps=None, change_id="alpha"):
        program = ("# Program — alpha\n\n## 风险等级\n\n- 等级：`low`\n\n"
                   "## 评估规则\n\n| id | 规则 | 通过依据 |\n| --- | --- | --- |\n"
                   "| `R1` | 验证 | 见步骤 |\n\n## 不验证及理由\n\n%s\n" % skip_line)
        return self.write_record(steps if steps is not None else [step()],
                                 change_id=change_id, program=program)

    def test_declared_skip_skips_probe(self):
        cid = self.write_program("- EditMode / PlayMode：不执行；不改 Unity 代码。")
        needed, _reason = harness_checks.requires_unity_probe(cid)
        self.assertFalse(needed)

    def test_unity_step_forces_probe(self):
        cid = self.write_program(
            "- EditMode：不执行。",
            steps=[step(role="evaluator", how="Linux Editor 进入 PlayMode",
                        observe=None,
                        needs_human_because=None)])
        needed, _reason = harness_checks.requires_unity_probe(cid)
        self.assertTrue(needed, "验证记录里有 Unity 步骤时不能跳过探针")

    def test_missing_program_is_conservative(self):
        needed, reason = harness_checks.requires_unity_probe("never-existed")
        self.assertTrue(needed)
        self.assertIn("保守", reason)

    def test_undeclared_scope_is_conservative(self):
        cid = self.write_program("- 无关条目：不执行。")
        needed, reason = harness_checks.requires_unity_probe(cid)
        self.assertTrue(needed)
        self.assertIn("保守", reason)

    def test_positive_wording_in_skip_section_is_conservative(self):
        """写在「不验证」里却说要执行：保守执行探针，不按小节标题一刀切。"""
        cid = self.write_program("- PlayMode：必须执行，见 tasks 3.2。")
        needed, _reason = harness_checks.requires_unity_probe(cid)
        self.assertTrue(needed)


class RiskFloorTests(ChecksTestCase):
    def test_high_risk_path_raises_floor(self):
        level, reasons = harness_checks.risk_floor(["Assets/A.prefab"])
        self.assertEqual(level, "high")
        self.assertTrue(reasons)

    def test_documents_do_not_raise_floor(self):
        level, _ = harness_checks.risk_floor(
            ["openspec/changes/persist-save/design.md", "docs/knowledge/save.md"])
        self.assertEqual(level, "low")

    def test_declaring_below_floor_is_rejected(self):
        cid = self.write_record([step()])
        problems = harness_checks.check_risk_floor(cid, ["Assets/A.shader"])
        self.assertTrue(any("低于机械下限" in p for p in problems), problems)

    def test_declaring_above_floor_is_accepted(self):
        cid = self.write_record([step()])
        self.assertEqual(harness_checks.check_risk_floor(cid, ["src/a.py"]), [])


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
        program = ("# Program\n\n## 风险等级\n\n- 等级：`low`\n\n## 评估规则\n\n"
                   "| id | 规则 | 通过依据 |\n| --- | --- | --- |\n"
                   "| `R1` | 验证 | 见步骤 |\n\n## 不验证及理由\n\n"
                   "- EditMode / PlayMode：不执行。\n")
        self.write_record([step()], program=program)
        self.assertEqual(self.run_check("probe-needed", "alpha").returncode, 1)

    def test_unknown_command_is_usage_error(self):
        self.assertEqual(self.run_check("bogus").returncode, 2)

    def test_verification_requires_change_argument(self):
        self.assertEqual(self.run_check("verification").returncode, 2)

    def test_gate_reports_missing_artifacts(self):
        (self.root / "openspec" / "changes" / "bare").mkdir(parents=True)
        out = self.run_check("gate", "bare")
        self.assertEqual(out.returncode, 1)
        self.assertIn("program.md", out.stderr)


if __name__ == "__main__":
    unittest.main()
