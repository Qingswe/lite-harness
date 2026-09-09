"""就绪度、质量文档预筛与看板步骤写回的回归测试。

覆盖旧实现完全没有的判据：证据路径存在性、规则覆盖、角色隔离，以及
「人工 phase 只能收紧不能放宽」这条唯一真正生效的覆盖规则。
"""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

DASHBOARD_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = DASHBOARD_DIR.parent / "scripts"
for path in (str(SCRIPTS_DIR), str(DASHBOARD_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

import harness_checks  # noqa: E402
import harness_state  # noqa: E402
import harness_verification as hv  # noqa: E402
import server  # noqa: E402


def _load_prescreen():
    spec = importlib.util.spec_from_file_location(
        "prescreen_quality_docs", SCRIPTS_DIR / "prescreen-quality-docs.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prescreen_mod = _load_prescreen()

PROGRAM = """# Program — alpha

## 风险等级

- 等级：`low`

## 评估规则

| id | 规则 | 通过依据 |
| --- | --- | --- |
| `R1` | 回归基线不退化 | 见步骤 |

## 必须验证

- 单元测试：跑 harness 回归套件。

## 不验证及理由

- EditMode：不执行，本 change 不触及 Unity 工程。

## 可观测性与回滚

- 日志：脚本 stderr。
- 回滚方式：git revert。
"""


def step(**overrides):
    base = {
        "id": "V1", "role": "evaluator", "tasks": ["1.1"], "rule": "R1",
        "how": "python3 -m unittest",
        "pass_when": "全部测试通过且总数不少于 54 项",
        "fail_when": "出现 FAIL 或 ERROR，或某个测试被静默跳过",
        "status": "pending", "operator": None, "date": None,
        "evaluated_by": None, "evidence": [], "note": None,
    }
    base.update(overrides)
    return base


class LoopTestCase(unittest.TestCase):
    def setUp(self):
        self._old_root = harness_state.ROOT
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "openspec" / "changes").mkdir(parents=True)
        (self.root / ".harness" / "evidence").mkdir(parents=True)
        harness_checks.configure_root(str(self.root))

    def tearDown(self):
        harness_checks.configure_root(self._old_root)
        self.temp.cleanup()

    def make_change(self, change_id="alpha", steps=None, done=1, total=1,
                    program=PROGRAM, prescreen="2026-07-30",
                    conclusion="passed", triggered=None):
        change = self.root / "openspec" / "changes" / change_id
        change.mkdir(parents=True, exist_ok=True)
        (change / "proposal.md").write_text("# %s\n" % change_id, encoding="utf-8")
        tasks = ["# Tasks", ""]
        for i in range(total):
            tasks.append("- [%s] %d.1 task" % ("x" if i < done else " ", i + 1))
        (change / "tasks.md").write_text("\n".join(tasks) + "\n", encoding="utf-8")
        if program is not None:
            (change / "program.md").write_text(program, encoding="utf-8")
        record = {
            "schema_version": 1, "change": change_id, "baseline_commit": "abc1234",
            "environment": {"os": "Linux", "unity": None, "date": "2026-07-30"},
            "steps": steps if steps is not None else [step()],
            "uncovered": [],
            "quality_docs": {"prescreen_run": prescreen,
                             "triggered": triggered or []},
            "conclusion": {"status": conclusion, "note": "ok"},
        }
        (change / "verification.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        return change_id

    def evidence(self, relpath=".harness/evidence/alpha/run.json"):
        target = self.root / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x", encoding="utf-8")
        return relpath

    def passed_step(self, **overrides):
        base = dict(status="passed", operator="qingswe", date="2026-07-30",
                    evaluated_by={"agent": "harness-evaluator",
                                  "model": "claude-sonnet-5"},
                    evidence=[self.evidence()])
        base.update(overrides)
        return step(**base)

    def readiness(self, change_id="alpha"):
        change = harness_state.build_change(change_id)
        return harness_checks.change_readiness(change, run_strict=False)


class ReadinessCriteriaTests(LoopTestCase):
    """七项判据里由本仓库拥有的五项，逐项构造反例。"""

    def test_all_criteria_met_is_ready(self):
        self.make_change(steps=[self.passed_step()])
        result = self.readiness()
        self.assertTrue(result["ready"], result["blockers"])

    def test_incomplete_tasks_block(self):
        self.make_change(steps=[self.passed_step()], done=0, total=2)
        blockers = self.readiness()["blockers"]
        self.assertTrue(any(b["criterion"] == "tasks" for b in blockers))

    def test_pending_step_blocks(self):
        self.make_change(steps=[step()])
        blockers = self.readiness()["blockers"]
        self.assertTrue(any(b["criterion"] == "step-status" for b in blockers))

    def test_missing_evidence_file_blocks(self):
        self.make_change(steps=[self.passed_step(
            evidence=[".harness/evidence/alpha/nope.json"])])
        result = self.readiness()
        self.assertFalse(result["ready"])
        self.assertTrue(any("nope.json" in b["detail"] for b in result["blockers"]))

    def test_uncovered_rule_blocks(self):
        program = PROGRAM.replace(
            "| `R1` | 回归基线不退化 | 见步骤 |",
            "| `R1` | 回归基线不退化 | 见步骤 |\n| `R2` | 另一条规则 | 见步骤 |")
        self.make_change(steps=[self.passed_step()], program=program)
        result = self.readiness()
        self.assertFalse(result["ready"])
        self.assertTrue(any("R2" in b["detail"] for b in result["blockers"]))

    def test_missing_prescreen_blocks(self):
        self.make_change(steps=[self.passed_step()], prescreen=None)
        blockers = self.readiness()["blockers"]
        self.assertTrue(any(b["criterion"] == "quality-prescreen"
                            for b in blockers))

    def test_triggered_entry_without_reason_blocks_and_is_human_owned(self):
        self.make_change(steps=[self.passed_step()],
                         triggered=[{"doc": "docs/quality/risks.md",
                                     "reason": ""}])
        blockers = self.readiness()["blockers"]
        match = [b for b in blockers if b["criterion"] == "quality-prescreen"]
        self.assertTrue(match)
        self.assertEqual("human", match[0]["owner"])

    def test_pending_conclusion_blocks(self):
        self.make_change(steps=[self.passed_step()], conclusion="pending")
        blockers = self.readiness()["blockers"]
        self.assertTrue(any(b["criterion"] == "conclusion" for b in blockers))

    def test_human_step_is_attributed_to_human(self):
        human = step(id="H1", role="human", how=None,
                     observe="打开 docs/quality/scorecard.md 的战斗评分行",
                     needs_human_because="需要产品判断，AI 无法产出证据")
        self.make_change(steps=[self.passed_step(), human])
        blockers = self.readiness()["blockers"]
        match = [b for b in blockers if "H1" in b["detail"]]
        self.assertTrue(match)
        self.assertEqual("human", match[0]["owner"])


class PhaseTighteningTests(LoopTestCase):
    """人工 phase 只能收紧不能放宽——这是唯一真正生效的覆盖规则。"""

    def _phase(self, explicit, steps):
        self.make_change(steps=steps)
        change = harness_state.build_change("alpha")
        return harness_state.derive_lifecycle(change, {"phase": explicit}, False)

    def test_human_may_tighten_to_blocked(self):
        phase, source, _ = self._phase("blocked", [self.passed_step()])
        self.assertEqual("blocked", phase)
        self.assertEqual("explicit", source)

    def test_human_may_not_claim_closable_when_not_ready(self):
        phase, source, warnings = self._phase("ready_to_close", [step()])
        self.assertNotEqual("ready_to_close", phase)
        self.assertEqual("derived", source)
        self.assertTrue(any("claims closable" in w for w in warnings))

    def test_descriptive_phase_is_honoured(self):
        """planned 与 awaiting_human 之间只有早晚之分，不该被硬排序覆盖。"""
        phase, source, _ = self._phase("awaiting_user_direction", [step()])
        self.assertEqual("awaiting_user_direction", phase)
        self.assertEqual("explicit", source)


class ReadyEnumerationTests(LoopTestCase):
    def test_change_absent_from_candidates_is_still_enumerated(self):
        """磁盘上存在但未登记为候选的 change 不能对 ready 隐身。

        否则一个真正就绪的 change 会永远触发不到自动归档，而且没有任何提示。
        """
        self.make_change("orphan", steps=[self.passed_step()])
        (self.root / ".harness" / "current.json").write_text(
            json.dumps({"schema_version": 2, "active_change": None,
                        "candidate_changes": [], "change_context": {}}),
            encoding="utf-8")
        report = harness_checks.build_ready_report(run_strict=False)
        seen = {i["change"] for i in report["ready"]} | \
               {i["change"] for i in report["blocked"]}
        self.assertIn("orphan", seen)


class BlockerAttributionTests(LoopTestCase):
    def test_human_blocker_outranks_pending_tasks(self):
        """有未作答人工步骤时，ready 必须报「等人」而不是「等 AI 做完 task」。

        剩下的 task 往往正依赖那个人工结论；报成 [AI] 会让人扫 ready 时漏掉
        自己那一条，这正是 V14 实测判失败的原因。
        """
        human = step(id="H1", role="human", how=None,
                     observe="打开 docs/quality/scorecard.md 的战斗评分行",
                     needs_human_because="需要产品判断")
        self.make_change(steps=[self.passed_step(), human], done=0, total=3)
        report = harness_checks.build_ready_report(run_strict=False)
        entry = next(i for i in report["blocked"] if i["change"] == "alpha")
        self.assertEqual("human", entry["owner"])
        self.assertIn("H1", entry["next_action"])

    def test_ai_blocker_used_when_no_human_pending(self):
        self.make_change(steps=[self.passed_step()], done=0, total=3)
        report = harness_checks.build_ready_report(run_strict=False)
        entry = next(i for i in report["blocked"] if i["change"] == "alpha")
        self.assertEqual("ai", entry["owner"])


class PrescreenTests(LoopTestCase):
    def setUp(self):
        super().setUp()
        prescreen_mod.configure_root(str(self.root))

    def test_untriggered_entries_produce_no_prose(self):
        """未触发的条目不产出说明文字——沉默即未触发。"""
        result = prescreen_mod.prescreen(self.make_change())
        docs = {item["doc"] for item in result["triggered"]}
        self.assertNotIn("docs/quality/tech-debt.md", docs)
        self.assertNotIn("docs/quality/risks.md", docs)

    def test_every_triggered_entry_carries_evidence(self):
        """脚本必须为「需要更新」举证，而不是让人为「不需要」辩护。"""
        result = prescreen_mod.prescreen(self.make_change())
        for item in result["triggered"]:
            self.assertTrue(item["evidence"], item)

    def test_manual_entries_are_questions_not_conclusions(self):
        result = prescreen_mod.prescreen(self.make_change())
        docs = {item["doc"] for item in result["manual"]}
        self.assertIn("docs/adr/", docs)
        self.assertIn("docs/knowledge/pitfalls/", docs)
        for item in result["manual"]:
            self.assertNotIn("reason", item)

    def test_write_back_preserves_existing_human_reason(self):
        cid = self.make_change(triggered=[{"doc": "docs/knowledge/changes/",
                                           "reason": "人写的理由"}])
        prescreen_mod.write_back(cid, prescreen_mod.prescreen(cid))
        data = hv.load_verification(cid)
        kept = [i for i in data["quality_docs"]["triggered"]
                if i["doc"] == "docs/knowledge/changes/"]
        self.assertEqual("人写的理由", kept[0]["reason"])


class DashboardStepWriteTests(LoopTestCase):
    def test_step_is_addressed_by_id_not_line(self):
        self.make_change(steps=[step(id="V1"), step(id="V2")])
        ok, status = harness_state.update_verification_step(
            "alpha", "V2", "passed", "qingswe", "2026-07-30", "note", None,
            [self.evidence()])
        self.assertTrue(ok)
        self.assertEqual("passed", status)
        data = hv.load_verification("alpha")
        self.assertEqual("pending", data["steps"][0]["status"])
        self.assertEqual("passed", data["steps"][1]["status"])

    def test_stale_expected_status_conflicts(self):
        self.make_change(steps=[step(id="V1")])
        ok, current = harness_state.update_verification_step(
            "alpha", "V1", "passed", "qingswe", "2026-07-30", "n", "passed",
            [self.evidence()])
        self.assertFalse(ok)
        self.assertEqual("pending", current)

    def test_no_consumer_parses_the_record_itself(self):
        """消费方不得把验证记录的**原文**自己解析一遍。

        Evaluator 实测到过这一条：`_statuses_at` 曾自己 json.loads 一个 git blob
        再摸 id/status，绕过唯一解析器，而当时的模块身份断言完全没看见它。
        索引 `load_verification()` 的返回值是消费解析结果，不在此列；把文本变成
        步骤的地方必须只有 harness_verification 一处。
        """
        scripts = DASHBOARD_DIR.parent / "scripts"
        for name in ("harness_checks.py", "harness_state.py"):
            lines = (scripts / name).read_text(encoding="utf-8").split("\n")
            for idx, line in enumerate(lines):
                if "json.loads" not in line and "json.load(" not in line:
                    continue
                context = "\n".join(lines[max(0, idx - 4):idx + 2])
                # 白名单：这几份 JSON 本来就归各自模块解析，与验证记录无关。
                allowed = ("CURRENT_JSON", "current.json",
                           "FEATURE_INDEX", "feature-index.json")
                self.assertTrue(
                    any(token in context for token in allowed),
                    "%s:%d 把 JSON 原文解析成了别的东西；验证记录的解析只能在 "
                    "harness_verification.parse_statuses" % (name, idx + 1))

class RoleIsolationTests(LoopTestCase):
    """角色隔离的机械强制。Evaluator 指出这块此前完全没有测试覆盖。"""

    def test_same_identity_evaluation_is_rejected(self):
        self.make_change(steps=[self.passed_step(
            evaluated_by={"agent": "claude-code", "model": "claude-opus-5"})])
        problems = harness_checks.check_role_isolation(
            "alpha", {"agent": "claude-code", "model": "claude-opus-5"})
        self.assertTrue(any("实现者不得评估自身产出" in p for p in problems),
                        problems)

    def test_same_model_different_agent_is_rejected(self):
        self.make_change(steps=[self.passed_step(
            evaluated_by={"agent": "other", "model": "claude-opus-5"})])
        problems = harness_checks.check_role_isolation(
            "alpha", {"agent": "claude-code", "model": "claude-opus-5"})
        self.assertTrue(any("必须换模型" in p for p in problems), problems)

    def test_distinct_identity_is_accepted(self):
        self.make_change(steps=[self.passed_step()])
        self.assertEqual([], harness_checks.check_role_isolation(
            "alpha", {"agent": "claude-code", "model": "claude-opus-5"}))

    def test_concluded_step_without_identity_is_rejected(self):
        self.make_change(steps=[self.passed_step(evaluated_by=None)])
        problems = harness_checks.check_role_isolation("alpha", {})
        self.assertTrue(any("没有记录评估身份" in p for p in problems), problems)

    def test_human_identity_is_exempt(self):
        human = step(id="H1", role="human", how=None,
                     observe="打开 docs/quality/scorecard.md 的战斗评分行",
                     needs_human_because="需要产品判断",
                     status="passed", operator="qingswe", date="2026-07-30",
                     evaluated_by={"agent": "human", "model": "human"},
                     evidence=[self.evidence()])
        self.make_change(steps=[human])
        self.assertEqual([], harness_checks.check_role_isolation(
            "alpha", {"agent": "human", "model": "human"}))

    def test_parse_step_identities_reads_evaluator_agent(self):
        blob = json.dumps({"steps": [
            {"id": "V1", "evaluated_by": {"agent": "Harness-Evaluator"}},
            {"id": "H1", "evaluated_by": {"agent": "human"}},
            {"id": "V2", "evaluated_by": None}]})
        got = hv.parse_step_identities(blob)
        self.assertEqual("harness-evaluator", got["V1"])
        self.assertEqual("human", got["H1"])
        self.assertEqual("", got["V2"])

    def test_parse_statuses_is_the_single_entry_point(self):
        blob = json.dumps({"steps": [{"id": "V1", "status": "PASSED"}]})
        self.assertEqual({"V1": "passed"}, hv.parse_statuses(blob))
        self.assertEqual({}, hv.parse_statuses("{not json"))
        self.assertEqual({}, hv.parse_statuses(None))


class ModifiedScenarioTests(LoopTestCase):
    """MODIFIED 块漏掉现有场景必须在 lint 报出，而不是拖到 archive 才炸。

    实测来源：simplify-harness-change-artifacts 自己的
    harness-human-check-format delta 把两条场景改了名，strict 校验通过、
    就绪度为真，直到 openspec archive 才拒绝——而 archive 是不可逆步骤。
    """

    def write_specs(self, current, delta, cap="cap-a",
                    change_id="alpha"):
        cur = self.root / "openspec" / "specs" / cap
        cur.mkdir(parents=True, exist_ok=True)
        (cur / "spec.md").write_text(current, encoding="utf-8")
        dlt = self.root / "openspec" / "changes" / change_id / "specs" / cap
        dlt.mkdir(parents=True, exist_ok=True)
        (dlt / "spec.md").write_text(delta, encoding="utf-8")

    def test_renamed_scenario_reads_as_dropped(self):
        self.make_change()
        self.write_specs(
            "## Purpose\n\n### Requirement: R\n\n#### Scenario: 空表格不得通过\n"
            "- **WHEN** a\n- **THEN** b\n",
            "## MODIFIED Requirements\n\n### Requirement: R\n\n"
            "#### Scenario: 空记录不得通过\n- **WHEN** a\n- **THEN** b\n")
        problems = harness_checks.check_modified_scenarios("alpha")
        self.assertEqual(1, len(problems))
        self.assertIn("空表格不得通过", problems[0])
        self.assertIn("REMOVED + ADDED", problems[0])

    def test_preserving_every_scenario_passes(self):
        self.make_change()
        self.write_specs(
            "## Purpose\n\n### Requirement: R\n\n#### Scenario: 甲\n"
            "- **WHEN** a\n- **THEN** b\n",
            "## MODIFIED Requirements\n\n### Requirement: R\n\n"
            "#### Scenario: 甲\n- **WHEN** a\n- **THEN** c\n\n"
            "#### Scenario: 乙\n- **WHEN** d\n- **THEN** e\n")
        self.assertEqual([], harness_checks.check_modified_scenarios("alpha"))

    def test_removed_plus_added_is_the_sanctioned_rename(self):
        self.make_change()
        self.write_specs(
            "## Purpose\n\n### Requirement: 旧名\n\n#### Scenario: 甲\n"
            "- **WHEN** a\n- **THEN** b\n",
            "## ADDED Requirements\n\n### Requirement: 新名\n\n"
            "#### Scenario: 甲\n- **WHEN** a\n- **THEN** b\n\n"
            "## REMOVED Requirements\n\n### Requirement: 旧名\n\n"
            "**Reason**: 换主语\n")
        self.assertEqual([], harness_checks.check_modified_scenarios("alpha"))

    def test_modifying_a_nonexistent_requirement_is_reported(self):
        self.make_change()
        self.write_specs(
            "## Purpose\n\n### Requirement: R\n\n#### Scenario: 甲\n"
            "- **WHEN** a\n- **THEN** b\n",
            "## MODIFIED Requirements\n\n### Requirement: 全新的\n\n"
            "#### Scenario: 乙\n- **WHEN** a\n- **THEN** b\n")
        problems = harness_checks.check_modified_scenarios("alpha")
        self.assertEqual(1, len(problems))
        self.assertIn("ADDED", problems[0])

    def test_close_gate_includes_the_check(self):
        self.make_change(steps=[self.passed_step()])
        self.write_specs(
            "## Purpose\n\n### Requirement: R\n\n#### Scenario: 甲\n"
            "- **WHEN** a\n- **THEN** b\n",
            "## MODIFIED Requirements\n\n### Requirement: R\n\n"
            "#### Scenario: 乙\n- **WHEN** a\n- **THEN** b\n")
        self.assertTrue(any("漏掉" in p
                            for p in harness_checks.close_gate("alpha")))


class FinalizeCloseTests(LoopTestCase):
    """归档后不得留下指向已归档 change 的下一个动作。"""

    def write_current(self, payload):
        (self.root / ".harness").mkdir(parents=True, exist_ok=True)
        (self.root / ".harness" / "current.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        harness_state.configure_root(str(self.root))

    def test_pointer_cleared_even_when_not_active(self):
        self.write_current({
            "schema_version": 2, "active_change": None,
            "candidate_changes": ["alpha", "beta"],
            "change_context": {"alpha": {"summary": "s"}},
            "current_task": "alpha：等待第四次人工判定",
            "next_action": "人工复核 alpha 的材料",
        })
        result = harness_state.finalize_close("alpha")
        loaded = harness_state.load_current()
        self.assertIsNone(loaded["current_task"])
        self.assertIsNone(loaded["next_action"])
        self.assertEqual(["beta"], loaded["candidate_changes"])
        self.assertFalse(result["released_active"])

    def test_unrelated_pointer_survives(self):
        self.write_current({
            "schema_version": 2, "active_change": None,
            "candidate_changes": ["alpha", "beta"],
            "change_context": {},
            "current_task": "beta：推进 3.1",
            "next_action": "继续 beta",
        })
        harness_state.finalize_close("alpha")
        loaded = harness_state.load_current()
        self.assertEqual("beta：推进 3.1", loaded["current_task"])
        self.assertEqual("继续 beta", loaded["next_action"])


class DashboardStepWriteTests2(LoopTestCase):
    def test_server_ready_endpoint_shares_one_implementation(self):
        self.assertIs(server.harness_checks.build_ready_report,
                      harness_checks.build_ready_report)


if __name__ == "__main__":
    unittest.main()
