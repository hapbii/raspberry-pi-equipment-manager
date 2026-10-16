from __future__ import annotations

import gc
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import weakref

from dotenv import dotenv_values

from equipment_manager import create_app
from equipment_manager.db import get_db
from equipment_manager.deployment import validate_deployment
from equipment_manager.detector_mode import ModeChangeError, _save_mode
from equipment_manager.vision.detector import MockDetector, YoloDetector


class DetectorModeTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.env = self.root / '.env'
        self.env.write_text("# keep this comment\nDETECTOR_MODE=mock # preview\nSECRET_KEY='private # value'\n", encoding='utf-8')
        self.model = self.root / 'model.pt'
        self.model.touch()
        self.app = create_app({
            'TESTING': True, 'CSRF_ENABLED': False, 'HEARTBEAT_ENABLED': False,
            'GPIO_ENABLED': False, 'DETECTOR_MODE': 'mock', 'ALLOW_MOCK_MODE': False,
            'DATABASE': str(self.root / 'test.db'), 'ERROR_LOG_PATH': str(self.root / 'errors.log'),
            'ENV_FILE_PATH': str(self.env), 'YOLO_MODEL_PATH': str(self.model),
            'SECRET_KEY': 'test-secret', 'DEVELOPER_USERNAME': 'developer',
            'DEVELOPER_PASSWORD': 'test-developer', 'TEACHER_USERNAME': 'teacher',
            'TEACHER_PASSWORD': 'test-teacher', 'DEFAULT_EQUIPMENT': ['breadboard'],
        })
        self.addCleanup(self.app.extensions['shutdown_services'])
        self.client = self.app.test_client()
        self.service = self.app.extensions['detection_service']

    def login(self, role='developer'):
        return self.client.post('/admin/login', data={'username': role, 'password': 'test-' + role})

    def switch(self, mode, expected, **kwargs):
        return self.client.post('/developer/detector-mode', data={'mode': mode, 'expected_mode': expected}, **kwargs)

    def test_round_trip_preserves_service_identity_and_other_env_settings(self):
        self.login()
        old = self.service._detector
        with patch.object(old, 'close', wraps=old.close) as closer:
            page = self.switch('yolo', 'mock', follow_redirects=True)
            closer.assert_called_once()
        self.assertIn('YOLO 모드로 변경했습니다', page.get_data(as_text=True))
        self.assertIs(self.service, self.app.extensions['detection_service'])
        self.assertIsInstance(self.service._detector, YoloDetector)
        self.assertIsNone(self.service._detector._model)
        self.assertEqual(self.app.config['DETECTOR_MODE'], 'yolo')
        self.assertFalse(self.app.config['ALLOW_MOCK_MODE'])
        self.assertEqual(dotenv_values(self.env)['DETECTOR_MODE'], 'yolo')
        self.assertIn('# keep this comment', self.env.read_text())
        self.assertIn("SECRET_KEY='private # value'", self.env.read_text())
        self.assertNotIn('private # value', page.get_data(as_text=True))
        yolo = self.service._detector
        with patch.object(yolo, 'close', wraps=yolo.close) as closer:
            self.switch('mock', 'yolo')
            closer.assert_called_once()
        self.assertIsInstance(self.service._detector, MockDetector)
        self.assertEqual(dotenv_values(self.env)['DETECTOR_MODE'], 'mock')
        self.assertEqual(dotenv_values(self.env)['ALLOW_MOCK_MODE'], 'true')
        self.assertTrue(self.app.config['ALLOW_MOCK_MODE'])
        self.assertEqual(self.service.status()['check_state'], 'unchecked')

    def test_busy_or_stale_request_cannot_change_settings(self):
        self.login()
        original = self.env.read_bytes()
        self.service._lock.acquire()
        try:
            page = self.switch('yolo', 'mock', follow_redirects=True)
        finally:
            self.service._lock.release()
        self.assertIn('완료 후 다시 시도', page.get_data(as_text=True))
        self.assertEqual(self.env.read_bytes(), original)
        self.switch('yolo', 'mock')
        changed = self.env.read_bytes()
        page = self.switch('yolo', 'mock', follow_redirects=True)
        self.assertIn('다른 요청에서 모드가 변경', page.get_data(as_text=True))
        self.assertEqual(self.env.read_bytes(), changed)
        self.assertEqual(self.app.config['DETECTOR_MODE'], 'yolo')

    def test_missing_model_invalid_mode_and_closed_service_do_not_change_env(self):
        self.login()
        original = self.env.read_bytes()
        self.model.unlink()
        page = self.switch('yolo', 'mock', follow_redirects=True)
        self.assertIn('모델을 읽을 수 없습니다', page.get_data(as_text=True))
        self.switch('bad', 'mock')
        self.model.touch()
        self.service.close()
        self.switch('yolo', 'mock')
        self.assertEqual(self.env.read_bytes(), original)
        self.assertEqual(self.app.config['DETECTOR_MODE'], 'mock')

    def test_partial_persistence_failure_keeps_old_backend_and_cleans_candidate(self):
        self.login()
        original = self.env.read_bytes()
        old = self.service._detector
        candidate = Mock(close=Mock())
        from dotenv import set_key
        def failing_second_key(*args, **kwargs):
            if args[1] == 'ALLOW_MOCK_MODE':
                raise OSError('write failed')
            return set_key(*args, **kwargs)
        with patch('equipment_manager.vision.service.build_detector', return_value=candidate), \
             patch('equipment_manager.detector_mode.set_key', side_effect=failing_second_key):
            page = self.switch('yolo', 'mock', follow_redirects=True)
        candidate.close.assert_called_once()
        self.assertIs(self.service._detector, old)
        self.assertEqual(self.app.config['DETECTOR_MODE'], 'mock')
        self.assertEqual(self.env.read_bytes(), original)
        self.assertFalse(list(self.root.glob('.env-mode-*.tmp')))
        self.assertIn('모드를 변경하지 못했습니다', page.get_data(as_text=True))

    def test_external_env_edit_is_not_overwritten(self):
        self.login()
        self.env.write_text('DETECTOR_MODE=yolo\nSECRET_KEY=external-change\n')
        original = self.env.read_bytes()
        page = self.switch('yolo', 'mock', follow_redirects=True)
        self.assertIn('실행 중인 모드와 다릅니다', page.get_data(as_text=True))
        self.assertEqual(self.env.read_bytes(), original)
        self.assertEqual(self.app.config['DETECTOR_MODE'], 'mock')

    def test_only_developer_with_csrf_can_change_mode(self):
        with patch('equipment_manager.routes.developer.switch_detector_mode') as switch:
            self.switch('yolo', 'mock')
            self.login('teacher')
            self.switch('yolo', 'mock')
            switch.assert_not_called()
        self.client.post('/logout')
        self.login()
        self.app.config['CSRF_ENABLED'] = True
        with patch('equipment_manager.routes.developer.switch_detector_mode') as switch:
            self.switch('yolo', 'mock')
            switch.assert_not_called()
        with self.client.session_transaction() as session:
            token = session['csrf_token']
        self.switch('yolo', 'mock', headers={'X-CSRF-Token': token})
        self.assertEqual(self.app.config['DETECTOR_MODE'], 'yolo')

    def test_production_mock_blocks_existing_scan_transaction(self):
        self.login('teacher')
        token = self.client.post('/api/scans', json={'mock_equipment_id': 1}).get_json()['scan']['token']
        self.app.config['TESTING'] = False
        response = self.client.post('/api/transactions', json={
            'scan_token': token, 'student_id': '30304', 'action': 'loan', 'quantity': 1, 'reason': 'class',
        })
        self.assertEqual(response.status_code, 422)
        with self.app.app_context():
            self.assertEqual(get_db().execute('SELECT COUNT(*) FROM transactions').fetchone()[0], 0)

    def test_repeated_switch_releases_retired_backends(self):
        self.login()
        references = []
        for _ in range(10):
            references.append(weakref.ref(self.service._detector))
            self.switch('yolo', 'mock')
            references.append(weakref.ref(self.service._detector))
            self.switch('mock', 'yolo')
        gc.collect()
        self.assertTrue(all(reference() is None for reference in references))
        self.assertFalse(self.service.status()['busy'])

    def test_saved_mock_flag_is_explicit_startup_opt_in(self):
        config = {
            'SECRET_KEY': 'private-key-at-least-thirty-two-characters',
            'DEVELOPER_USERNAME': 'developer', 'DEVELOPER_PASSWORD': 'private-developer-password',
            'TEACHER_USERNAME': 'teacher', 'TEACHER_PASSWORD': 'private-teacher-password',
            'DETECTOR_MODE': 'mock', 'ALLOW_MOCK_MODE': True,
        }
        validate_deployment(config, self.root)
        for value in (False, 'false', 'true', None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_deployment(config | {'ALLOW_MOCK_MODE': value}, self.root)
        with self.assertRaisesRegex(ValueError, 'YOLO_MODEL_PATH'):
            validate_deployment(config | {'DETECTOR_MODE': 'yolo'}, self.root)

    def test_mode_cannot_change_between_transaction_check_and_commit(self):
        self.login('teacher')
        token = self.client.post('/api/scans', json={'mock_equipment_id': 1}).get_json()['scan']['token']
        from equipment_manager.inventory import commit_transaction
        from equipment_manager.vision import DetectionError
        def commit_while_attempting_switch(**kwargs):
            with self.assertRaises(DetectionError):
                self.service.switch_mode(self.app.config, 'yolo', 'mock', Mock())
            return commit_transaction(**kwargs)
        with patch('equipment_manager.routes.station.commit_transaction', side_effect=commit_while_attempting_switch):
            response = self.client.post('/api/transactions', json={
                'scan_token': token, 'student_id': '30304', 'action': 'loan', 'quantity': 1, 'reason': 'class',
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.app.config['DETECTOR_MODE'], 'mock')
        self.assertFalse(self.service.status()['busy'])

    def test_multiline_values_survive_atomic_env_write(self):
        original = "DETECTOR_MODE=mock\nSECRET_KEY='line one\nDETECTOR_MODE=inside-secret\nline three'\nexport OTHER='a # b'\n"
        self.env.write_text(original, encoding='utf-8')
        _save_mode(self.env, 'yolo', 'mock')
        before = dotenv_values(stream=io.StringIO(original))
        after = dotenv_values(self.env)
        self.assertEqual(before['SECRET_KEY'], after['SECRET_KEY'])
        self.assertEqual(before['OTHER'], after['OTHER'])
        self.assertEqual(after['DETECTOR_MODE'], 'yolo')
        with patch.object(Path, 'is_symlink', return_value=True), self.assertRaises(ModeChangeError):
            _save_mode(self.env, 'mock', 'yolo')


if __name__ == '__main__':
    unittest.main()
