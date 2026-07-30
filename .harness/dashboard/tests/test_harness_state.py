"""共享状态模块与 `harness status` 的回归测试。

覆盖 dashboard 既有测试没有覆盖的部分：CLI 与看板共用同一实现、漂移检测、
证据子目录列举，以及 status 在状态不一致时以非零码退出。
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
        for name in ("build_state", "normalize_current_state", "derive_lifecycle",
                     "update_current_state", "existing_change_ids"):
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
        """两平台子命令必须一致，否则同一个 change 在两台机器上结论不同。"""
        scripts = DASHBOARD_DIR.parent / "scripts"
        bash = (scripts / "harness").read_text(encoding="utf-8")
        pwsh = (scripts / "harness.ps1").read_text(encoding="utf-8")
        for command in ("status", "ready", "next", "lint", "render", "verify",
                        "close", "rollback", "autoclose", "sync-candidates",
                        "reset-current"):
            self.assertIn('"%s"' % command, pwsh,
                          "harness.ps1 缺少子命令 %s" % command)
            self.assertIn(command, bash, "harness 缺少子命令 %s" % command)


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


class DriftDetectionTests(TempRepoTestCase):
    def test_clean_when_membership_matches_directories(self):
        self.make_change("alpha")
        self.make_change("beta")
        self.write_current(active_change="alpha", candidate_changes=["beta"])
        status = harness_state.build_status(commit_count=0)
        self.assertTrue(status["drift"]["clean"], status["drift"])

    def test_reports_change_dir_missing_from_current(self):
        self.make_change("alpha")
        self.make_change("orphan")
        self.write_current(active_change="alpha")
        drift = harness_state.build_status(commit_count=0)["drift"]
        self.assertFalse(drift["clean"])
        self.assertEqual(drift["missing_from_current"], ["orphan"])

    def test_reports_stale_entry_without_directory(self):
        self.make_change("alpha")
        self.write_current(candidate_changes=["alpha", "archived-already"])
        drift = harness_state.build_status(commit_count=0)["drift"]
        self.assertFalse(drift["clean"])
        self.assertIn("archived-already", drift["stale_in_current"])

    def test_active_change_alone_is_not_reported_missing(self):
        self.make_change("alpha")
        self.write_current(active_change="alpha")
        drift = harness_state.build_status(commit_count=0)["drift"]
        self.assertTrue(drift["clean"], drift)


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
        self.assertEqual(payload["active_change"], "alpha")
        self.assertEqual(payload["active"]["tasks"], "1/2")
        self.assertTrue(payload["drift"]["clean"])

    def test_drift_makes_status_exit_nonzero(self):
        self.make_change("alpha")
        self.make_change("orphan")
        self.write_current(active_change="alpha")
        proc = self.run_status()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("orphan", proc.stdout)

    def test_unknown_argument_is_rejected(self):
        proc = self.run_status("--bogus")
        self.assertEqual(proc.returncode, 2)

    def test_text_output_reports_empty_active_slot(self):
        self.make_change("alpha")
        self.write_current(candidate_changes=["alpha"])
        proc = self.run_status()
        self.assertIn("Active 执行槽: 空", proc.stdout)


if __name__ == "__main__":
    unittest.main()


class CurrentStateSchemaTests(TempRepoTestCase):
    def test_reset_current_emits_all_fields_in_use(self):
        harness_state.reset_current_state()
        state = json.loads(
            (self.root / ".harness" / "current.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(state), sorted(harness_state.CURRENT_STATE_FIELDS))
        for field in ("deleted_files", "last_change_note", "verification_summary"):
            self.assertIn(field, state)

    def test_reset_current_cli_matches_module_schema(self):
        proc = subprocess.run(
            [sys.executable, str(STATE_SCRIPT), "reset-current",
             "--root", str(self.root)],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        state = json.loads(
            (self.root / ".harness" / "current.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(state), sorted(harness_state.CURRENT_STATE_FIELDS))

    def test_both_platform_scripts_delegate_reset_to_shared_module(self):
        scripts_dir = SCRIPTS_DIR
        bash = (scripts_dir / "harness").read_text(encoding="utf-8")
        ps1 = (scripts_dir / "harness.ps1").read_text(encoding="utf-8")
        for source, name in ((bash, "harness"), (ps1, "harness.ps1")):
            self.assertIn("harness_state.py", source)
            self.assertNotIn('"schema_version": 2', source,
                             "%s 仍自带 current.json 字面量模板" % name)


class ContextAuditTests(TempRepoTestCase):
    def base_context(self, **overrides):
        context = {"summary": "短摘要", "phase": "planned", "blockers": [],
                   "depends_on": [], "next_action": "等待人工晋升。",
                   "last_checkpoint": None}
        context.update(overrides)
        return context

    def test_structured_context_passes(self):
        self.make_change("alpha")
        self.write_current(candidate_changes=["alpha"],
                           change_context={"alpha": self.base_context()})
        self.assertEqual(harness_state.audit_change_context(
            harness_state.load_current()), [])

    def test_oversized_summary_is_reported(self):
        self.make_change("alpha")
        self.write_current(candidate_changes=["alpha"], change_context={
            "alpha": self.base_context(summary="很长的摘要" * 40)})
        problems = harness_state.audit_change_context(harness_state.load_current())
        self.assertTrue(any("超过上限" in p for p in problems), problems)

    def test_missing_and_unknown_fields_are_reported(self):
        self.make_change("alpha")
        self.write_current(candidate_changes=["alpha"], change_context={
            "alpha": {"summary": "只有摘要", "notes": "野字段"}})
        problems = harness_state.audit_change_context(harness_state.load_current())
        self.assertTrue(any("缺少字段" in p for p in problems), problems)
        self.assertTrue(any("未知 context 字段" in p for p in problems), problems)

    def test_unknown_phase_is_reported(self):
        self.make_change("alpha")
        self.write_current(candidate_changes=["alpha"], change_context={
            "alpha": self.base_context(phase="active")})
        problems = harness_state.audit_change_context(harness_state.load_current())
        self.assertTrue(any("未知 phase" in p for p in problems), problems)


class SyncCandidatesTests(TempRepoTestCase):
    def test_membership_is_derived_from_change_directories(self):
        self.make_change("alpha")
        self.make_change("beta")
        self.make_change("gamma")
        self.write_current(active_change="alpha",
                           candidate_changes=["beta", "already-archived"])
        result = harness_state.sync_candidates()
        self.assertEqual(result["after"], ["beta", "gamma"])
        self.assertEqual(result["added"], ["gamma"])
        self.assertEqual(result["removed"], ["already-archived"])

    def test_sync_makes_status_clean(self):
        self.make_change("alpha")
        self.make_change("orphan")
        self.write_current(active_change="alpha")
        self.assertFalse(harness_state.build_status(commit_count=0)["drift"]["clean"])
        harness_state.sync_candidates()
        self.assertTrue(harness_state.build_status(commit_count=0)["drift"]["clean"])

    def test_sync_preserves_per_change_context(self):
        self.make_change("alpha")
        self.make_change("beta")
        self.write_current(active_change="alpha", change_context={
            "beta": {"summary": "保留我", "phase": "planned", "next_action": "等待"}})
        harness_state.sync_candidates()
        state = json.loads(
            (self.root / ".harness" / "current.json").read_text(encoding="utf-8"))
        self.assertEqual(state["change_context"]["beta"]["summary"], "保留我")


class FinalizeCloseTests(TempRepoTestCase):
    def test_removes_candidate_and_context_entries(self):
        self.make_change("alpha")
        self.make_change("beta")
        self.write_current(candidate_changes=["alpha", "beta"], change_context={
            "alpha": {"summary": "a", "phase": "ready_to_close", "next_action": "x"},
            "beta": {"summary": "b", "phase": "planned", "next_action": "y"}})
        result = harness_state.finalize_close("alpha")
        state = json.loads(
            (self.root / ".harness" / "current.json").read_text(encoding="utf-8"))
        self.assertEqual(state["candidate_changes"], ["beta"])
        self.assertNotIn("alpha", state["change_context"])
        self.assertIn("beta", state["change_context"])
        self.assertFalse(result["released_active"])

    def test_releases_active_slot_and_verification_summary(self):
        self.make_change("alpha")
        self.write_current(active_change="alpha", current_task="做 alpha",
                           working_files=["a.md"],
                           verification_summary={"active_change": "alpha",
                                                 "phase": "active"})
        result = harness_state.finalize_close("alpha")
        state = json.loads(
            (self.root / ".harness" / "current.json").read_text(encoding="utf-8"))
        self.assertIsNone(state["active_change"])
        self.assertIsNone(state["current_task"])
        self.assertEqual(state["working_files"], [])
        self.assertIsNone(state["verification_summary"]["active_change"])
        self.assertTrue(result["released_active"])

    def test_unrelated_change_is_untouched(self):
        self.make_change("alpha")
        self.write_current(active_change="alpha", candidate_changes=[])
        result = harness_state.finalize_close("never-existed")
        state = json.loads(
            (self.root / ".harness" / "current.json").read_text(encoding="utf-8"))
        self.assertEqual(state["active_change"], "alpha")
        self.assertEqual(result["cleared"], [])

    def test_cli_finalize_close_requires_exactly_one_change(self):
        for args in ([], ["a", "b"]):
            proc = subprocess.run(
                [sys.executable, str(STATE_SCRIPT), "finalize-close",
                 "--root", str(self.root), *args],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(proc.returncode, 2, proc.stdout)
