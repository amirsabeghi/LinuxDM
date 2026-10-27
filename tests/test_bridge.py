import io
import json
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from linuxdm.bridge import AppInstance, drain_inbox, enqueue, submit, submit_capture, settle_capture, write_json
from linuxdm.chrome_install import extension_id, install
from linuxdm.engine import DownloadManager
from linuxdm.native_host import handle_message, read_message, write_message


class BridgeTest(unittest.TestCase):
    def test_capture_is_acknowledged_without_waiting_for_the_user_dialog(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = DownloadManager(Path(tmp) / 'state')
            try:
                result = submit_capture('https://example.invalid/incoming.zip', 'e' * 32,
                                        root=manager.root, probe=lambda *_: None,
                                        launch=lambda: drain_inbox(manager, tmp, 4, awaiting_confirmation=True))
                self.assertTrue(result['ok'])
                self.assertEqual(manager.snapshot()[0]['status'], 'Ready')
                self.assertTrue(manager.snapshot()[0]['needs_confirmation'])
                self.assertFalse(manager.active)
            finally:
                manager.close()

    def test_automatic_capture_preserves_filename_and_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = DownloadManager(Path(tmp) / 'state')
            manager.parallel = 0
            try:
                request_id = 'a' * 32
                result = submit_capture('https://example.com/opaque-token', request_id,
                                        filename='../../archive.zip', root=manager.root,
                                        probe=lambda *_: None,
                                        launch=lambda: drain_inbox(manager, tmp, 4))
                self.assertTrue(result['ok'])
                self.assertEqual(manager.snapshot()[0]['target'], str(Path(tmp) / 'archive.zip'))
                self.assertTrue(settle_capture(request_id, manager.root)['ok'])
                # Recover ownership even if the acknowledgement file is lost.
                (manager.root / 'inbox' / f'{request_id}.result').unlink()
                self.assertTrue(settle_capture(request_id, manager.root)['ok'])
            finally:
                manager.close()

    def test_capture_timeout_cannot_create_a_late_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = DownloadManager(Path(tmp) / 'state')
            manager.parallel = 0
            try:
                request_id = 'b' * 32
                result = submit_capture('https://example.com/file.zip', request_id, root=manager.root,
                                        probe=lambda *_: None, launch=lambda: None, timeout=0)
                self.assertFalse(result['ok'])
                self.assertFalse(list((manager.root / 'inbox').glob('*.json')))
                self.assertEqual(drain_inbox(manager, tmp, 4), [])
                # A delayed retry of the original native process is rejected too.
                again = submit_capture('https://example.com/file.zip', request_id, root=manager.root,
                                       probe=lambda *_: self.fail('Cancelled capture was probed again'))
                self.assertFalse(again['ok'])
                self.assertEqual(manager.snapshot(), [])
            finally:
                manager.close()

    def test_expired_capture_and_rejected_probe_never_enter_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = DownloadManager(Path(tmp) / 'state')
            manager.parallel = 0
            try:
                request_id = enqueue('https://example.com/file.zip', manager.root)
                path = manager.root / 'inbox' / f'{request_id}.json'
                write_json(path, {'url': 'https://example.com/file.zip', 'expires': 0})
                self.assertEqual(drain_inbox(manager, tmp, 4), [])
                def failed_probe(*_):
                    raise OSError('Login required')
                result = submit_capture('https://example.com/private.zip', 'c' * 32,
                                        root=manager.root, probe=failed_probe,
                                        launch=lambda: self.fail('App launched for a rejected capture'))
                self.assertFalse(result['ok'])
                self.assertEqual(manager.snapshot(), [])
            finally:
                manager.close()

    def test_native_protocol_and_bad_messages(self):
        stream = io.BytesIO()
        write_message(stream, {'action': 'download', 'url': 'https://example.com/مورد.zip'})
        stream.seek(0)
        self.assertIn('مورد', read_message(stream)['url'])
        for data in (b'\x01', struct.pack('=I', 70000), struct.pack('=I', 10) + b'{}'):
            with self.assertRaises(ValueError):
                read_message(io.BytesIO(data))
        self.assertTrue(handle_message({'action': 'ping'})['ok'])
        with self.assertRaises(ValueError):
            handle_message({'action': 'unknown'})

    def test_partial_reads(self):
        class Pipe(io.BytesIO):
            def read(self, n=-1):
                return super().read(min(n, 2))
        raw = io.BytesIO()
        write_message(raw, {'action': 'ping'})
        self.assertEqual(read_message(Pipe(raw.getvalue())), {'action': 'ping'})

    def test_invalid_urls_never_enter_inbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            for url in ('file:///etc/passwd', 'javascript:alert(1)', 'https://', 'https://x/\n', None):
                with self.assertRaises(ValueError):
                    enqueue(url, tmp)
            self.assertFalse((Path(tmp) / 'inbox').exists())

    def test_single_instance_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            with AppInstance(tmp) as first:
                self.assertTrue(first.acquired)
                with AppInstance(tmp) as second:
                    self.assertFalse(second.acquired)
            with AppInstance(tmp) as later:
                self.assertTrue(later.acquired)

    def test_handoff_and_duplicate_request_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'state'
            manager = DownloadManager(root)
            manager.parallel = 0
            try:
                request_id = enqueue('https://example.com/file.zip', root)
                path = root / 'inbox' / f'{request_id}.json'
                original = path.read_text()
                self.assertEqual(drain_inbox(manager, tmp, 4), [request_id])
                self.assertTrue(json.loads(path.with_suffix('.result').read_text())['ok'])
                self.assertEqual(manager.snapshot()[0]['url'], 'https://example.com/file.zip')
                self.assertFalse(path.exists())
                # A crash between queue save and acknowledgement must not add a second job.
                path.write_text(original)
                drain_inbox(manager, tmp, 4)
                self.assertEqual(len(manager.snapshot()), 1)
            finally:
                manager.close()

    def test_submit_starts_app_and_waits_for_queue_acknowledgement(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = DownloadManager(Path(tmp) / 'state')
            manager.parallel = 0
            try:
                def launch():
                    drain_inbox(manager, tmp, 4)
                result = submit('https://example.com/file.zip', manager.root, launch=launch)
                self.assertTrue(result['ok'])
                self.assertNotIn('pending', result)
                self.assertEqual(len(manager.snapshot()), 1)
                self.assertFalse(list((manager.root / 'inbox').glob('*.result')))
            finally:
                manager.close()

    def test_running_app_is_not_launched_again_and_link_remains_durable(self):
        with tempfile.TemporaryDirectory() as tmp:
            with AppInstance(tmp), patch('linuxdm.bridge.launch_app') as launch:
                result = submit('https://example.com/file.zip', tmp, launch=launch, timeout=0)
                launch.assert_not_called()
            self.assertTrue(result['pending'])
            self.assertEqual(len(list((Path(tmp) / 'inbox').glob('*.json'))), 1)

    def test_installer_and_real_native_host_ping(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(__file__).resolve().parent.parent
            paths = install(Path(tmp) / 'config', Path(tmp) / 'data with spaces', project)
            manifest = json.loads(paths[0].read_text())
            self.assertEqual(manifest['allowed_origins'], [f'chrome-extension://{extension_id(project)}/'])
            data = io.BytesIO()
            write_message(data, {'action': 'ping'})
            result = subprocess.run([manifest['path']], input=data.getvalue(), capture_output=True, check=True)
            self.assertEqual(result.stderr, b'')
            self.assertTrue(read_message(io.BytesIO(result.stdout))['ok'])
