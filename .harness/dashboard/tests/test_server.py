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


    def test_tasks_drive_progress_without_state_file(self):
        self.make_change("active-owner", done=1, total=2)
        state = server.build_state()
        change = next(c for c in state["changes"] if c["id"] == "active-owner")
        self.assertEqual(change["task_progress"], {"done": 1, "total": 2})
        self.assertEqual(change["lifecycle_phase"], "implementing")
        self.assertFalse((self.root / ".harness/current.json").exists())

    def test_human_checks_remain_visible_without_active(self):
        self.make_change("released-human", done=1, total=1, checks=["pending"])
        state = server.build_state()
        self.assertIn("released-human", state["queues"]["awaiting_human"])
        self.assertIsNone(state["current"]["active_change"])
