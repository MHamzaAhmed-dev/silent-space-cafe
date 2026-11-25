import importlib.util
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('release', Path(__file__).resolve().parents[1] / 'deploy/release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseGateTests(unittest.TestCase):
    def setUp(self):
        self.sha = 'a' * 40
        self.ci_run = dict(id=1, head_sha=self.sha, head_branch='main', event='push',
            head_repository={'full_name': 'owner/cafe'}, path='.github/workflows/ci.yml',
            status='completed', conclusion='success', html_url='https://github.com/owner/cafe/actions/runs/1')

    def test_exact_main_push_success_is_required(self):
        self.assertEqual(release.passed_run({'workflow_runs': [self.ci_run]}, self.sha, 'owner/cafe'), self.ci_run['html_url'])
        for changes in ({'head_sha': 'b' * 40}, {'head_branch': 'other'}, {'event': 'pull_request'},
                        {'conclusion': 'failure'}, {'status': 'in_progress'}, {'path': 'other.yml'},
                        {'head_repository': {'full_name': 'other/cafe'}}):
            with self.subTest(changes=changes), self.assertRaises(RuntimeError):
                release.passed_run({'workflow_runs': [dict(self.ci_run, **changes)]}, self.sha, 'owner/cafe')

    def test_later_failure_cannot_reuse_previous_success(self):
        failed = dict(self.ci_run, id=2, conclusion='failure')
        with self.assertRaises(RuntimeError):
            release.passed_run({'workflow_runs': [self.ci_run, failed]}, self.sha, 'owner/cafe')

    def test_sqlite_backup_preserves_data_without_editing_source(self):
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder) / 'source.db', Path(folder) / 'backup.db'
            with closing(sqlite3.connect(source)) as db:
                db.execute('CREATE TABLE example (reference TEXT)')
                db.execute("INSERT INTO example VALUES ('original-private-reference')")
                db.commit()
            self.assertTrue(release.backup_database(source, target))
            for path in (source, target):
                with closing(sqlite3.connect(path)) as db:
                    self.assertEqual(db.execute('SELECT reference FROM example').fetchone()[0], 'original-private-reference')
            self.assertFalse(release.backup_database(Path(folder) / 'absent.db', target))
