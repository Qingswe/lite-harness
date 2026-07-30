"""verification.json 与 program.md 契约的回归测试。

重点覆盖旧实现完全没有的拒绝路径：取反的失败标准、不存在的证据、规则双向
覆盖不全、按 role 的必填字段，以及迁移前形态必须报错而不是被当成"没有未完成项"。
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

DASHBOARD_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = DASHBOARD_DIR.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import harness_verification as hv  # noqa: E402


PROGRAM_LOW = """# Program — alpha

## 风险等级

- 等级：`low`

## 评估规则

| id | 规则 | 通过依据 |
| --- | --- | --- |
| `R1` | 回归基线不退化 | 全部测试通过 |

## 必须验证

- 单元测试：跑 harness 回归套件。

## 不验证及理由

- EditMode：不执行，本 change 不触及 UnityProject/。

## 可观测性与回滚

- 日志：脚本 stderr。
- 回滚方式：git revert。
"""


def step(**overrides):
    base = {
        "id": "V1",
        "role": "evaluator",
        "tasks": ["1.1"],
        "rule": "R1",
        "how": "python3 -m unittest",
        "pass_when": "全部测试通过且总数不少于 54 项",
        "fail_when": "出现 FAIL 或 ERROR，或总数少于 54 项",
        "status": "pending",
        "operator": None,
        "date": None,
        "evaluated_by": None,
        "evidence": [],
        "note": None,
    }
    base.update(overrides)
    return base


def record(steps=None, **overrides):
    base = {
        "schema_version": 1,
        "change": "alpha",
        "baseline_commit": "abc1234",
        "environment": {"os": "Linux", "unity": None, "date": "2026-07-30"},
        "steps": steps if steps is not None else [step()],
        "uncovered": [],
        "quality_docs": {"prescreen_run": None, "triggered": []},
        "conclusion": {"status": "pending", "note": None},
    }
    base.update(overrides)
    return base


class VerificationTestCase(unittest.TestCase):
    def setUp(self):
        self._old_root = hv.ROOT
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "openspec" / "changes").mkdir(parents=True)
        hv.configure_root(str(self.root))

    def tearDown(self):
        hv.configure_root(self._old_root)
        self.temp.cleanup()

    def write(self, data, program=PROGRAM_LOW, change_id="alpha"):
        change = self.root / "openspec" / "changes" / change_id
        change.mkdir(parents=True, exist_ok=True)
        if data is not None:
            (change / "verification.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        if program is not None:
            (change / "program.md").write_text(program, encoding="utf-8")
        return change_id

    def write_evidence(self, relpath, change_id="alpha"):
        target = self.root / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("evidence", encoding="utf-8")
        return relpath

    def assertProblem(self, problems, fragment):
        self.assertTrue(any(fragment in p for p in problems),
                        "期望命中 %r，实际: %s" % (fragment, problems))


class WellFormedRecordTests(VerificationTestCase):
    def test_pending_record_passes_lint(self):
        """实现尚未开始的合规记录必须能通过 lint，否则「门槛随时可跑」落空。"""
        cid = self.write(record())
        self.assertEqual(hv.lint(cid), [])

    def test_pending_record_is_not_ready(self):
        cid = self.write(record())
        result = hv.verification_readiness(cid)
        self.assertFalse(result["ready"])
        self.assertTrue(any(b["criterion"] == "step-status"
                            for b in result["blockers"]))

    def test_all_steps_parsed_regardless_of_count(self):
        """首表截断类失效不可能重现：步骤数量与顺序不影响解析完整性。"""
        steps = [step(id="V%d" % i) for i in range(1, 8)]
        cid = self.write(record(steps))
        data = hv.load_verification(cid)
        self.assertEqual(len(data["steps"]), 7)
        self.assertEqual(hv.step_counts(data["steps"])["pending"], 7)


class FieldContractTests(VerificationTestCase):
    def test_missing_required_field_is_rejected(self):
        cid = self.write(record([step(pass_when="")]))
        self.assertProblem(hv.lint(cid), "缺少必填字段 pass_when")

    def test_duplicate_step_id_is_rejected(self):
        cid = self.write(record([step(id="V1"), step(id="V1")]))
        self.assertProblem(hv.lint(cid), "重复")

    def test_invalid_role_is_rejected(self):
        cid = self.write(record([step(role="reviewer")]))
        self.assertProblem(hv.lint(cid), "必须是 evaluator/human/external 之一")

    def test_human_step_requires_observe_and_reason(self):
        cid = self.write(record([step(role="human", how=None)]))
        problems = hv.lint(cid)
        self.assertProblem(problems, "缺少必填字段 observe")
        self.assertProblem(problems, "缺少必填字段 needs_human_because")

    def test_evaluator_step_requires_how(self):
        cid = self.write(record([step(how="")]))
        self.assertProblem(hv.lint(cid), "缺少必填字段 how")

    def test_bad_date_format_is_rejected(self):
        cid = self.write(record([step(date="2026/07/30")]))
        self.assertProblem(hv.lint(cid), "必须是 YYYY-MM-DD")


class NegationDetectionTests(VerificationTestCase):
    def test_identical_criteria_rejected(self):
        cid = self.write(record([step(pass_when="全部测试通过",
                                      fail_when="全部测试通过")]))
        self.assertProblem(hv.lint(cid), "只是 pass_when 的取反")

    def test_leading_negation_rejected(self):
        cid = self.write(record([step(pass_when="全部测试通过",
                                      fail_when="不是全部测试通过")]))
        self.assertProblem(hv.lint(cid), "只是 pass_when 的取反")

    def test_trailing_negation_rejected(self):
        cid = self.write(record([step(pass_when="全部测试通过",
                                      fail_when="全部测试通过不成立")]))
        self.assertProblem(hv.lint(cid), "只是 pass_when 的取反")

    def test_english_negation_rejected(self):
        cid = self.write(record([step(pass_when="all tests pass",
                                      fail_when="not all tests pass")]))
        self.assertProblem(hv.lint(cid), "只是 pass_when 的取反")

    def test_concrete_failure_mode_accepted(self):
        """描述具体错法的失败标准必须被接受，否则规则会逼人写废话。"""
        cid = self.write(record([step(
            pass_when="全部测试通过且总数不少于 54 项",
            fail_when="出现 FAIL 或 ERROR，或某个测试被静默跳过")]))
        self.assertEqual(hv.lint(cid), [])

    def test_too_short_criterion_is_rejected(self):
        cid = self.write(record([step(fail_when="失败")]))
        problems = hv.lint(cid)
        self.assertTrue(any("过短" in p or "取反" in p for p in problems), problems)


class EvidenceTests(VerificationTestCase):
    def _concluded(self, **overrides):
        base = dict(status="passed", operator="qingswe", date="2026-07-30",
                    evaluated_by={"agent": "harness-evaluator",
                                  "model": "claude-sonnet-5"},
                    evidence=[".harness/evidence/alpha/run.json"])
        base.update(overrides)
        return step(**base)

    def test_missing_evidence_file_is_rejected(self):
        cid = self.write(record([self._concluded()]))
        self.assertProblem(hv.lint(cid), "引用了不存在的证据")

    def test_existing_evidence_file_is_accepted(self):
        self.write_evidence(".harness/evidence/alpha/run.json")
        cid = self.write(record([self._concluded()]))
        self.assertEqual(hv.lint(cid), [])

    def test_concluded_step_without_evidence_is_rejected(self):
        cid = self.write(record([self._concluded(evidence=[])]))
        self.assertProblem(hv.lint(cid), "没有引用任何证据")

    def test_concluded_step_requires_evaluated_by(self):
        self.write_evidence(".harness/evidence/alpha/run.json")
        cid = self.write(record([self._concluded(evaluated_by=None)]))
        self.assertProblem(hv.lint(cid), "缺少 evaluated_by.agent")

    def test_waived_without_note_is_rejected(self):
        self.write_evidence(".harness/evidence/alpha/run.json")
        cid = self.write(record([self._concluded(status="waived", note="")]))
        self.assertProblem(hv.lint(cid), "缺少豁免说明")


class RuleCoverageTests(VerificationTestCase):
    def test_unknown_rule_reference_is_rejected(self):
        cid = self.write(record([step(rule="R9")]))
        self.assertProblem(hv.lint(cid), "不存在于 program.md")

    def test_unreferenced_rule_is_rejected_at_lint(self):
        program = PROGRAM_LOW.replace(
            "| `R1` | 回归基线不退化 | 全部测试通过 |",
            "| `R1` | 回归基线不退化 | 全部测试通过 |\n| `R2` | 无人引用 | 见设计 |")
        cid = self.write(record(), program=program)
        self.assertProblem(hv.lint(cid), "没有任何步骤引用它")

    def test_uncovered_rule_blocks_readiness_but_not_lint(self):
        """有步骤引用但尚未通过：lint 放行，就绪度拦住。"""
        cid = self.write(record())
        self.assertEqual(hv.lint(cid), [])
        blockers = hv.verification_readiness(cid)["blockers"]
        self.assertTrue(any(b["criterion"] == "rule-coverage" for b in blockers))


class ProgramContractTests(VerificationTestCase):
    def test_missing_program_is_rejected(self):
        cid = self.write(record(), program=None)
        self.assertProblem(hv.lint(cid), "找不到")

    def test_missing_risk_level_is_rejected(self):
        program = PROGRAM_LOW.replace("- 等级：`low`", "- 等级：")
        cid = self.write(record(), program=program)
        self.assertProblem(hv.lint(cid), "未声明有效等级")

    def test_high_risk_requires_more_sections(self):
        program = PROGRAM_LOW.replace("- 等级：`low`", "- 等级：`high`")
        cid = self.write(record(), program=program)
        problems = hv.lint(cid)
        self.assertProblem(problems, "缺少必需小节「约束」")
        self.assertProblem(problems, "缺少必需小节「停止条件」")

    def test_placeholder_section_is_reported(self):
        program = PROGRAM_LOW.replace(
            "- EditMode：不执行，本 change 不触及 UnityProject/。", "- 不适用")
        cid = self.write(record(), program=program)
        self.assertProblem(hv.lint(cid), "整节均为占位内容")

    def test_rules_parsed_from_bullets(self):
        program = ("# Program\n\n## 风险等级\n\n- 等级：`low`\n\n"
                   "## 评估规则\n\n- `R1` 回归基线不退化\n\n"
                   "## 必须验证\n\n- 单元测试：回归套件。\n\n"
                   "## 不验证及理由\n\n- EditMode：不执行，不触及 Unity。\n\n"
                   "## 可观测性与回滚\n\n- 日志：stderr。\n- 回滚方式：git revert。\n")
        cid = self.write(record(), program=program)
        self.assertEqual(hv.lint(cid), [])


class LegacyFormatTests(VerificationTestCase):
    def test_legacy_only_change_is_reported_not_silently_clean(self):
        """未迁移的 change 必须报错，而不是因为解析不到步骤就判定无未完成项。"""
        change = self.root / "openspec" / "changes" / "legacy"
        change.mkdir(parents=True)
        (change / "human-checks.md").write_text("本阶段无必须人工检查项。",
                                                encoding="utf-8")
        problems = hv.lint("legacy")
        self.assertProblem(problems, "仍是迁移前形态")

    def test_both_formats_present_is_rejected(self):
        cid = self.write(record())
        change = self.root / "openspec" / "changes" / cid
        (change / "human-checks.md").write_text("旧表格", encoding="utf-8")
        self.assertProblem(hv.lint(cid), "两份事实来源必须收敛")

    def test_unsupported_schema_version_is_rejected(self):
        cid = self.write(record(schema_version=99))
        self.assertProblem(hv.lint(cid), "只支持 1")

    def test_broken_json_is_reported(self):
        change = self.root / "openspec" / "changes" / "broken"
        change.mkdir(parents=True)
        (change / "verification.json").write_text("{not json", encoding="utf-8")
        self.assertProblem(hv.lint("broken"), "解析失败")


class WriteTests(VerificationTestCase):
    def test_set_step_by_id(self):
        self.write_evidence(".harness/evidence/alpha/run.json")
        cid = self.write(record())
        hv.set_step(cid, "V1", "passed", operator="qingswe",
                    date_value="2026-07-30",
                    evidence=[".harness/evidence/alpha/run.json"],
                    agent="harness-evaluator", model="claude-sonnet-5")
        data = hv.load_verification(cid)
        self.assertEqual(data["steps"][0]["status"], "passed")
        self.assertEqual(data["steps"][0]["evaluated_by"]["agent"],
                         "harness-evaluator")

    def test_expected_status_mismatch_conflicts(self):
        cid = self.write(record())
        with self.assertRaises(hv.StepConflict):
            hv.set_step(cid, "V1", "passed", expected_status="passed")

    def test_waived_requires_note(self):
        cid = self.write(record())
        with self.assertRaises(ValueError):
            hv.set_step(cid, "V1", "waived", operator="qingswe")

    def test_unknown_step_id_is_rejected(self):
        cid = self.write(record())
        with self.assertRaises(ValueError):
            hv.set_step(cid, "V99", "passed")

    def test_write_preserves_other_steps(self):
        self.write_evidence(".harness/evidence/alpha/run.json")
        cid = self.write(record([step(id="V1"), step(id="V2")]))
        hv.set_step(cid, "V2", "passed", operator="qingswe",
                    evidence=[".harness/evidence/alpha/run.json"],
                    agent="harness-evaluator", model="claude-sonnet-5")
        data = hv.load_verification(cid)
        self.assertEqual(data["steps"][0]["status"], "pending")
        self.assertEqual(data["steps"][1]["status"], "passed")


class RenderTests(VerificationTestCase):
    def test_render_includes_every_step(self):
        cid = self.write(record([step(id="V1"), step(id="V2", rule="R1")]))
        out = hv.render_markdown(cid)
        self.assertIn("V1", out)
        self.assertIn("V2", out)
        self.assertIn("## 判定契约", out)


if __name__ == "__main__":
    unittest.main()
