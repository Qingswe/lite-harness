import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


DASHBOARD_DIR = Path(__file__).resolve().parents[1]
if str(DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_DIR))

import server  # noqa: E402


FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "execution-context.json").read_text(
        encoding="utf-8"))


class HarnessStateTests(unittest.TestCase):
    def setUp(self):
        self._old_root = server.ROOT
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / ".harness").mkdir()
        (self.root / "openspec" / "changes").mkdir(parents=True)
        for change_id in (
                "released-human", "direction-gated", "active-owner",
                "planned-candidate"):
            self.make_change(change_id)
        server.configure_root(str(self.root))

    def tearDown(self):
        server.configure_root(self._old_root)
        self.temp.cleanup()

    def make_change(self, change_id, done=0, total=1, checks=None):
        change = self.root / "openspec" / "changes" / change_id
        change.mkdir(parents=True, exist_ok=True)
        (change / "proposal.md").write_text(
            "# %s\n" % change_id, encoding="utf-8")
        tasks = ["# Tasks", ""]
        for index in range(total):
            tasks.append("- [%s] task %d" % ("x" if index < done else " ", index + 1))
        (change / "tasks.md").write_text("\n".join(tasks) + "\n", encoding="utf-8")
        if checks is not None:
            # 人工检查已并入 verification.json 的 role: human 步骤；
            # checks 里的每个状态生成一个人工步骤。
            (change / "program.md").write_text(
                "# Program\n\n## 风险等级\n\n- 等级：`low`\n\n## 评估规则\n\n"
                "| id | 规则 | 通过依据 |\n| --- | --- | --- |\n"
                "| `R1` | 人工确认 | 见步骤 |\n\n## 不验证及理由\n\n"
                "- EditMode：不执行，此为夹具。\n\n"
                "## 必须验证\n\n- 夹具：无实际验证。\n\n"
                "## 可观测性与回滚\n\n- 日志：无。\n- 回滚方式：无。\n", encoding="utf-8")
            steps = []
            for index, status in enumerate(checks):
                steps.append({
                    "id": "H%d" % (index + 1), "role": "human", "tasks": [],
                    "rule": "R1",
                    "observe": "夹具检查项 %d 的观察对象" % (index + 1),
                    "pass_when": "夹具检查项 %d 的通过标准" % (index + 1),
                    "fail_when": "夹具检查项 %d 出现具体的错误表现" % (index + 1),
                    "needs_human_because": "夹具：需要人工确认",
                    "status": status, "operator": None, "date": None,
                    "evaluated_by": None, "evidence": [], "note": None,
                    "migrated": True,
                })
            record = {
                "schema_version": 1, "change": change_id,
                "baseline_commit": None,
                "environment": {"os": None, "unity": None, "date": None},
                "steps": steps, "uncovered": [],
                "quality_docs": {"prescreen_run": None, "triggered": []},
                "conclusion": {"status": "pending", "note": None},
            }
            (change / "verification.json").write_text(
                json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8")

    def write_current(self, state):
        (self.root / ".harness" / "current.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")

    def read_current(self):
        return json.loads(
            (self.root / ".harness" / "current.json").read_text(encoding="utf-8"))

    def test_legacy_annotations_normalize_and_preserve_all_text(self):
        result = server.normalize_current_state(
            FIXTURES["legacy_annotated"], server.existing_change_ids())
        self.assertFalse(result["errors"])
        self.assertTrue(result["migration_pending"])
        self.assertEqual(
            ["released-human", "direction-gated"],
            result["state"]["candidate_changes"])
        summary = result["state"]["change_context"]["released-human"]["summary"]
        self.assertIn("Automatic verification complete", summary)
        self.assertIn("duplicate annotation", summary)

    def test_malformed_legacy_entry_blocks_mutation(self):
        self.write_current(FIXTURES["malformed_legacy"])
        with self.assertRaises(server.StateMigrationError):
            server.update_current_state("add-candidate", "planned-candidate")
        self.assertEqual(
            FIXTURES["malformed_legacy"]["candidate_changes"],
            self.read_current()["candidate_changes"])

    def test_explicit_released_phase_is_independent_from_membership(self):
        self.make_change(
            "released-human", done=0, total=1,
            checks=["pending", "pending", "pending"])
        state = copy.deepcopy(FIXTURES["released_human_and_direction"])
        self.write_current(state)
        projected = server.build_state()
        change = next(
            item for item in projected["changes"]
            if item["id"] == "released-human")
        self.assertFalse(change["is_active"])
        self.assertTrue(change["is_candidate"])
        self.assertEqual(
            "awaiting_human_and_user_direction", change["lifecycle_phase"])
        self.assertEqual("explicit", change["phase_source"])
        self.assertEqual(3, change["check_counts"]["pending"])
        self.assertIn(
            "released-human",
            projected["queues"]["awaiting_user_direction"])

    def test_activation_conflict_returns_without_modifying_state(self):
        state = copy.deepcopy(FIXTURES["active_owner"])
        self.write_current(state)
        before = self.read_current()
        with self.assertRaises(server.StateConflict):
            server.update_current_state("set-active", "planned-candidate")
        self.assertEqual(before, self.read_current())

    def test_candidate_mutation_changes_membership_only(self):
        state = copy.deepcopy(FIXTURES["canonical_v2"])
        self.write_current(state)
        tasks_before = (
            self.root / "openspec" / "changes" / "planned-candidate" /
            "tasks.md").read_text(encoding="utf-8")
        server.update_current_state("add-candidate", "planned-candidate")
        saved = self.read_current()
        self.assertIn("planned-candidate", saved["candidate_changes"])
        self.assertEqual(
            state["change_context"], saved["change_context"])
        self.assertEqual(
            tasks_before,
            (self.root / "openspec" / "changes" / "planned-candidate" /
             "tasks.md").read_text(encoding="utf-8"))

    def test_release_preserves_recovery_and_clears_only_working_files(self):
        state = copy.deepcopy(FIXTURES["active_owner"])
        state.update({
            "current_task": "Implement task 2.4.",
            "working_files": ["one.py"],
            "blockers": ["Human review is required."],
            "next_action": "Run review.",
            "last_checkpoint": ".harness/checkpoints/active-owner/latest.md",
            "dirty_assumptions": ["Keep this durable note."],
            "verification_summary": {
                "active_change": "active-owner",
                "phase": "auto-verified-awaiting-human",
            },
        })
        self.write_current(state)
        server.update_current_state("clear-active")
        saved = self.read_current()
        context = saved["change_context"]["active-owner"]
        self.assertIsNone(saved["active_change"])
        self.assertIsNone(saved["current_task"])
        self.assertIsNone(saved["verification_summary"]["active_change"])
        self.assertEqual([], saved["working_files"])
        self.assertEqual(["Human review is required."], saved["blockers"])
        self.assertEqual("Run review.", saved["next_action"])
        self.assertEqual(
            ".harness/checkpoints/active-owner/latest.md",
            saved["last_checkpoint"])
        self.assertEqual(
            ["Keep this durable note."], saved["dirty_assumptions"])
        self.assertEqual(saved["blockers"], context["blockers"])
        self.assertEqual(saved["next_action"], context["next_action"])
        self.assertEqual(saved["last_checkpoint"], context["last_checkpoint"])
        self.assertIn("active-owner", saved["candidate_changes"])

    def test_empty_ghost_change_dir_is_not_discoverable(self):
        ghost = self.root / "openspec" / "changes" / "ghost-after-failed-archive"
        ghost.mkdir(parents=True, exist_ok=True)
        self.write_current({
            "schema_version": 2,
            "active_change": None,
            "candidate_changes": [],
            "change_context": {},
        })
        projected = server.build_state()
        ids = [item["id"] for item in projected["changes"]]
        self.assertNotIn("ghost-after-failed-archive", ids)
        self.assertNotIn(
            "ghost-after-failed-archive", server.existing_change_ids())


if __name__ == "__main__":
    unittest.main()
