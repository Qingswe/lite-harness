"""State is derived from OpenSpec, with no global execution-state writes."""
import json
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from test_harness_loop import LoopTestCase
import harness_checks
import harness_state
import server


class OpenSpecQueryTests(LoopTestCase):
    def metadata(self, data):
        path = self.root / 'openspec/changes/alpha/program.md'
        text = re.sub(r'^```harness-metadata\n.*?^```\n', '', path.read_text(), flags=re.M | re.S)
        path.write_text(text + '\n```harness-metadata\n' + json.dumps(data) + '\n```\n')

    def test_empty_repository_needs_no_current(self):
        state = harness_state.build_state()
        self.assertEqual(state['changes'], [])
        self.assertFalse((self.root / '.harness/current.json').exists())

    def test_invalid_legacy_current_is_ignored_and_preserved(self):
        self.make_change('alpha')
        path = self.root / '.harness/current.json'
        path.parent.mkdir(exist_ok=True)
        path.write_text('old state is not a query input')
        state = harness_state.build_state()
        self.assertEqual([c['id'] for c in state['changes']], ['alpha'])
        self.assertFalse(state['current']['parse_error'])
        self.assertEqual(path.read_text(), 'old state is not a query input')

    def test_archive_removes_change_without_cleanup(self):
        self.make_change('alpha')
        self.make_change('beta')
        archive = self.root / 'openspec/changes/archive'
        archive.mkdir()
        shutil.move(str(self.root / 'openspec/changes/alpha'), str(archive / '2026-09-09-alpha'))
        state = harness_state.build_state()
        self.assertEqual([c['id'] for c in state['changes']], ['beta'])
        self.assertFalse((self.root / '.harness/current.json').exists())

    def test_next_uses_explicit_change_and_writes_nothing(self):
        self.make_change('alpha', done=False)
        self.make_change('beta', done=False)
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        action = harness_checks.build_next_action(run_strict=False, change_id='beta')
        self.assertEqual((action['action'], action['change']), ('implement', 'beta'))
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_no_target_requests_selection_without_persistent_slot(self):
        self.make_change('alpha', done=False)
        self.assertEqual(harness_checks.build_next_action(False)['action'], 'select-change')

    def test_missing_explicit_target_is_not_silently_replaced(self):
        self.make_change('alpha')
        self.assertEqual(harness_checks.build_next_action(False, 'absent')['action'], 'resolve')

    def test_identity_comes_from_change_program(self):
        self.make_change('alpha')
        identity = {'agent': 'generator', 'model': 'model-a'}
        self.metadata({'generated_by': identity})
        self.assertEqual(harness_checks.generator_identity('alpha'), identity)

    def test_blocker_applies_to_next_ready_and_close(self):
        self.make_change('alpha')
        self.metadata({'blockers': ['waiting for product decision']})
        self.assertEqual(harness_checks.build_next_action(False, 'alpha')['action'], 'resolve')
        self.assertIn('waiting for product decision', harness_checks.close_gate('alpha'))
        self.assertFalse(harness_checks.change_readiness(harness_state.build_change('alpha'), False)['ready'])

    def test_dependency_blocks_until_archive(self):
        self.make_change('alpha')
        self.make_change('beta')
        self.metadata({'depends_on': ['beta']})
        self.assertTrue(harness_checks.metadata_blockers('alpha'))
        archive = self.root / 'openspec/changes/archive'
        archive.mkdir()
        shutil.move(str(self.root / 'openspec/changes/beta'), str(archive / '2026-09-09-beta'))
        self.assertEqual(harness_checks.metadata_blockers('alpha'), [])
        state = harness_state.build_state()
        self.assertEqual(state['changes'][0]['recovery']['depends_on'], ['beta'])

    def test_invalid_metadata_blocks_queries_and_gate(self):
        self.make_change('alpha')
        self.metadata({'current_task': 'duplicate state'})
        self.assertTrue(harness_state.build_state()['current']['parse_error'])
        self.assertTrue(harness_checks.metadata_blockers('alpha'))
        self.assertEqual(harness_checks.build_next_action(False, 'alpha')['action'], 'resolve')

    def test_duplicate_metadata_is_rejected(self):
        self.make_change('alpha')
        self.metadata({})
        path = self.root / 'openspec/changes/alpha/program.md'
        path.write_text(path.read_text() + '\n```harness-metadata\n{}\n```\n')
        self.assertTrue(harness_checks.metadata_blockers('alpha'))

    def test_metadata_types_are_validated(self):
        self.make_change('alpha')
        self.metadata({'depends_on': 'beta'})
        self.assertTrue(harness_checks.metadata_blockers('alpha'))

    def test_next_cli_accepts_target(self):
        self.make_change('alpha', done=False)
        script = Path(harness_checks.__file__)
        result = subprocess.run([sys.executable, str(script), 'next', 'alpha', '--json', '--root', str(self.root), '--no-strict'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['action'], 'implement')

    def test_global_state_write_route_is_removed(self):
        routes = {item['route'] for item in server.DATA_FLOW}
        self.assertNotIn('/api/current', routes)

    def test_missing_generator_cannot_bypass_independent_evaluation(self):
        self.make_change('alpha', steps=[self.passed_step()])
        self.metadata({})
        self.assertTrue(any('generated_by' in p for p in harness_checks.close_gate('alpha')))
