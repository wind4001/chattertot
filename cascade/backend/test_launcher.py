import importlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((Path(__file__).resolve().parents[2]/'manage.py').is_file(),'One-click launcher is missing')
        self.manage=importlib.import_module('manage')

    def test_foreign_port_occupant_is_rejected_without_killing_it(self):
        with patch.object(self.manage,'port_open',return_value=True), patch.object(self.manage,'read_json',return_value={'service':'another-app'}):
            with self.assertRaisesRegex(self.manage.StartupError,'占用'):
                self.manage.existing_backend(8080,False)

    def test_same_workspace_and_mode_can_be_reused(self):
        identity={'service':'chattertot','project_id':self.manage.project_id(),'mode':'production'}
        with patch.object(self.manage,'port_open',return_value=True), patch.object(self.manage,'read_json',return_value=identity):
            self.assertTrue(self.manage.existing_backend(8080,False))

    def test_another_checkout_cannot_be_mistaken_for_this_project(self):
        identity={'service':'chattertot','project_id':'other-checkout','mode':'production'}
        with patch.object(self.manage,'port_open',return_value=True), patch.object(self.manage,'read_json',return_value=identity):
            with self.assertRaises(self.manage.StartupError):
                self.manage.existing_backend(8080,False)

    def test_test_mode_uses_isolated_database_and_preserves_explicit_key_overrides(self):
        with patch.dict(self.manage.os.environ,{'DB_URL':'postgresql://u:pw@localhost/lym','LLM_API_KEY':'old-process-key'}):
            env=self.manage.child_env(True)
        self.assertTrue(env['DB_URL'].endswith('/lym_test'))
        self.assertEqual(env['CHATTERTOT_RUN_MODE'],'test')
        self.assertEqual(env['LLM_API_KEY'],'old-process-key')

    def test_preflight_rejects_missing_env_without_installing_or_starting(self):
        with patch.object(self.manage,'ENV_FILE',Path('nonexistent-env-for-test')):
            with self.assertRaisesRegex(self.manage.StartupError,'.env'):
                self.manage.require_configuration_file()

    def test_concurrent_start_is_rejected_and_lock_releases_after_exit(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(self.manage, 'ROOT', Path(folder)):
            with self.manage.startup_lock(8081):
                with self.assertRaisesRegex(self.manage.StartupError, '启动流程'):
                    with self.manage.startup_lock(8081):
                        self.fail('Concurrent start acquired the same lock')
            with self.manage.startup_lock(8081):
                pass

    def test_doctor_never_installs_or_starts_services(self):
        with (
            patch.object(self.manage, 'require_configuration_file'),
            patch.object(self.manage, 'check_docker'),
            patch.object(self.manage, 'dependencies_ready', return_value=True),
            patch.object(self.manage, 'health_report', return_value={'status':'ready','checks':[]}),
            patch.object(self.manage, 'existing_backend', return_value=True),
            patch.object(self.manage, 'ensure_environment', side_effect=AssertionError('Doctor installed dependencies')),
            patch.object(self.manage, 'prepare_services', side_effect=AssertionError('Doctor changed Docker services')),
            patch.object(self.manage, 'start_backend', side_effect=AssertionError('Doctor started backend')),
        ):
            self.assertEqual(self.manage.doctor(8080), 0)


if __name__=='__main__':
    unittest.main()
