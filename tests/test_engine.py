import http.server
import tempfile
import threading
import time
import unittest
from pathlib import Path
from linuxdm.engine import DownloadManager
from linuxdm.bridge import drain_inbox, submit_capture

DATA = bytes(range(256)) * 6000


class Handler(http.server.BaseHTTPRequestHandler):
    requests = []
    request_lock = threading.Lock()

    def log_message(self, *args):
        pass

    def do_GET(self):
        ranged = not self.path.startswith('/plain') and self.headers.get('Range')
        start, end = 0, len(DATA) - 1
        if ranged:
            start, end = map(int, self.headers['Range'][6:].split('-'))
        with self.request_lock:
            self.requests.append((self.path, start, end))
        self.send_response(206 if ranged else 200)
        self.send_header('Content-Length', str(end - start + 1))
        self.send_header('ETag', '"test-v1"')
        if ranged:
            self.send_header('Content-Range', f'bytes {start}-{end}/{len(DATA)}')
        self.end_headers()
        try:
            for offset in range(start, end + 1, 8192):
                self.wfile.write(DATA[offset:min(offset + 8192, end + 1)])
                self.wfile.flush()
                if 'slow' in self.path:
                    time.sleep(.015)
        except (BrokenPipeError, ConnectionResetError):
            pass


class EngineTest(unittest.TestCase):
    def test_global_slots_are_shared_between_named_queues(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = DownloadManager(Path(tmp) / 'state')
            try:
                with manager.lock:
                    first = manager.save_queue('First', 2)
                    second = manager.save_queue('Second', 2)
                    for queue in (first, second):
                        for index in range(2):
                            manager.add(f'http://127.0.0.1:{self.server.server_port}/slow-fair-{queue}-{index}',
                                        tmp, connections=1, queue_id=queue)
                self.wait_for(lambda: len(manager.active) == 2)
                jobs = manager.snapshot()
                self.assertEqual({j['queue_id'] for j in jobs if j['id'] in manager.active}, {first, second})
            finally:
                self.stop(manager)
    def test_queue_limits_and_independent_pause_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = DownloadManager(Path(tmp) / 'state')
            try:
                with manager.lock:
                    manager.parallel = 4
                    first = manager.save_queue('First', 1)
                    second = manager.save_queue('Second', 2)
                    for queue in (first, second):
                        for index in range(3):
                            manager.add(f'http://127.0.0.1:{self.server.server_port}/slow-{queue}-{index}',
                                        tmp, connections=1, queue_id=queue)
                self.wait_for(lambda: len(manager.active) == 3)
                jobs = manager.snapshot()
                self.assertEqual(sum(j['queue_id'] == first and j['status'] == 'Downloading' for j in jobs), 1)
                self.assertEqual(sum(j['queue_id'] == second and j['status'] == 'Downloading' for j in jobs), 2)
                manager.pause_queue(first)
                self.wait_for(lambda: not any(j['queue_id'] == first and j['id'] in manager.active for j in manager.snapshot()))
                self.assertTrue(any(j['queue_id'] == second and j['id'] in manager.active for j in manager.snapshot()))
                manager.pause_queue(first, False)
                self.wait_for(lambda: any(j['queue_id'] == first and j['status'] == 'Downloading' for j in manager.snapshot()))
            finally:
                self.stop(manager)

    def test_remove_active_download_waits_for_workers_and_cleans_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = DownloadManager(Path(tmp) / 'state')
            try:
                job_id = manager.add(f'http://127.0.0.1:{self.server.server_port}/slow-remove', tmp, 4)
                self.wait_for(lambda: manager.snapshot()[0]['done'] >= 65536)
                target = Path(manager.snapshot()[0]['target'])
                with manager.lock:
                    manager.remove(job_id)
                    self.assertEqual(manager.snapshot()[0]['status'], 'Removing')
                self.wait_for(lambda: not manager.active and not manager.snapshot())
                self.assertFalse((manager.root / job_id).exists())
                self.assertFalse(target.exists())
                self.stop(manager)
                manager = DownloadManager(Path(tmp) / 'state')
                self.assertEqual(manager.snapshot(), [])
            finally:
                self.stop(manager)

    def test_clear_completed_preserves_files_and_unfinished_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = DownloadManager(Path(tmp) / 'state')
            try:
                completed = manager.add(f'http://127.0.0.1:{self.server.server_port}/completed', tmp)
                self.wait_for(lambda: manager.snapshot()[0]['status'] == 'Complete')
                self.wait_for(lambda: not manager.active)
                target = Path(manager.snapshot()[0]['target'])
                manager.parallel = 0
                queued = manager.add('https://example.invalid/queued', tmp)
                paused = manager.add('https://example.invalid/paused', tmp)
                manager.pause(paused)
                manager.clear_completed()
                self.assertEqual({j['id'] for j in manager.snapshot()}, {queued, paused})
                self.assertEqual(target.read_bytes(), DATA)
                self.assertFalse((manager.root / completed).exists())
                manager.remove(queued)
                self.assertEqual(manager.snapshot()[0]['id'], paused)
            finally:
                self.stop(manager)

    def test_browser_choice_is_persisted_and_only_starts_when_confirmed(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = DownloadManager(Path(tmp) / 'state')
            try:
                job_id = manager.add(f'http://127.0.0.1:{self.server.server_port}/incoming', tmp,
                                     awaiting_confirmation=True)
                self.assertEqual(manager.snapshot()[0]['status'], 'Ready')
                self.stop(manager)
                manager = DownloadManager(Path(tmp) / 'state')
                self.assertTrue(manager.snapshot()[0]['needs_confirmation'])
                Path(tmp, 'chosen.zip').write_bytes(b'existing file')
                manager.confirm(job_id, tmp, 'chosen.zip', 2, start=False)
                job = manager.snapshot()[0]
                self.assertEqual(job['status'], 'Paused')
                self.assertFalse(job['needs_confirmation'])
                self.assertEqual(Path(job['target']).name, 'chosen (1).zip')
                manager.resume(job_id)
                self.wait_for(lambda: manager.snapshot()[0]['status'] in ('Complete', 'Error'))
                job = manager.snapshot()[0]
                self.assertEqual(job['status'], 'Complete', job['error'])
                self.assertEqual(Path(job['target']).read_bytes(), DATA)
                self.assertEqual(Path(tmp, 'chosen.zip').read_bytes(), b'existing file')
            finally:
                self.stop(manager)

    def test_browser_capture_probes_and_downloads_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = DownloadManager(Path(tmp) / 'state')
            try:
                result = submit_capture(f'http://127.0.0.1:{self.server.server_port}/captured',
                                        'd' * 32, filename='browser-name.zip', root=manager.root,
                                        launch=lambda: drain_inbox(manager, tmp, 4))
                self.assertTrue(result['ok'])
                self.wait_for(lambda: manager.snapshot()[0]['status'] in ('Complete', 'Error'))
                job = manager.snapshot()[0]
                self.assertEqual(job['status'], 'Complete', job['error'])
                self.assertEqual(Path(job['target']).name, 'browser-name.zip')
                self.assertEqual(Path(job['target']).read_bytes(), DATA)
            finally:
                self.stop(manager)

    def wait_for(self, predicate, timeout=12):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(.01)
        self.fail('Timed out waiting for download state')

    def stop(self, manager):
        manager.close()
        self.wait_for(lambda: not manager.active)

    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_range_and_single_connection(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = DownloadManager(Path(tmp) / 'state')
            try:
                for name in ('ranged', 'plain'):
                    manager.add(f'http://127.0.0.1:{self.server.server_port}/{name}', tmp, 4)
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if all(j['status'] in ('Complete', 'Error') for j in manager.snapshot()):
                        break
                    time.sleep(.05)
                for job in manager.snapshot():
                    self.assertEqual(job['status'], 'Complete', job['error'])
                    self.assertEqual(Path(job['target']).read_bytes(), DATA)
            finally:
                self.stop(manager)

    def test_validation_and_queue_pause(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = DownloadManager(Path(tmp) / 'state')
            try:
                manager.parallel = 0
                with self.assertRaises(ValueError):
                    manager.add('file:///etc/passwd', tmp)
                job_id = manager.add('https://example.com/file', tmp)
                manager.pause(job_id)
                self.assertEqual(manager.snapshot()[0]['status'], 'Paused')
                manager.resume(job_id)
                self.assertEqual(manager.snapshot()[0]['status'], 'Queued')
            finally:
                self.stop(manager)

    def test_pause_resume_reuses_partial_ranges_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = DownloadManager(Path(tmp) / 'state')
            try:
                job_id = manager.add(f'http://127.0.0.1:{self.server.server_port}/slow-resume', tmp, 4)
                self.wait_for(lambda: manager.snapshot()[0]['done'] >= 65536)
                manager.pause(job_id)
                self.wait_for(lambda: manager.snapshot()[0]['status'] == 'Paused')
                saved = manager.snapshot()[0]['done']
                self.assertGreater(saved, 0)
                self.assertLess(saved, len(DATA))
                time.sleep(.08)
                self.assertEqual(saved, manager.snapshot()[0]['done'])
                self.stop(manager)
                manager = DownloadManager(Path(tmp) / 'state')
                self.assertEqual(manager.snapshot()[0]['status'], 'Paused')
                with Handler.request_lock:
                    marker = len(Handler.requests)
                manager.resume(job_id)
                self.wait_for(lambda: manager.snapshot()[0]['status'] in ('Complete', 'Error'))
                job = manager.snapshot()[0]
                self.assertEqual(job['status'], 'Complete', job['error'])
                self.assertEqual(Path(job['target']).read_bytes(), DATA)
                with Handler.request_lock:
                    ranges = [r for r in Handler.requests[marker:] if r[0] == '/slow-resume' and r[2] != 0]
                self.assertTrue(ranges)
                self.assertLess(sum(end - start + 1 for _, start, end in ranges), len(DATA))
            finally:
                self.stop(manager)

    def test_resume_requested_while_connections_are_stopping(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = DownloadManager(Path(tmp) / 'state')
            try:
                job_id = manager.add(f'http://127.0.0.1:{self.server.server_port}/slow-immediate', tmp, 4)
                self.wait_for(lambda: manager.snapshot()[0]['done'] >= 32768)
                with manager.lock:
                    manager.pause(job_id)
                    self.assertEqual(manager.snapshot()[0]['status'], 'Pausing')
                    manager.resume(job_id)
                    self.assertEqual(manager.snapshot()[0]['status'], 'Resuming')
                self.wait_for(lambda: manager.snapshot()[0]['status'] in ('Complete', 'Error'))
                job = manager.snapshot()[0]
                self.assertEqual(job['status'], 'Complete', job['error'])
                self.assertEqual(Path(job['target']).read_bytes(), DATA)
            finally:
                self.stop(manager)

    def test_pause_resume_without_range_support_restarts_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = DownloadManager(Path(tmp) / 'state')
            try:
                job_id = manager.add(f'http://127.0.0.1:{self.server.server_port}/plain-slow', tmp, 4)
                self.wait_for(lambda: manager.snapshot()[0]['done'] >= 32768)
                manager.pause(job_id)
                self.wait_for(lambda: manager.snapshot()[0]['status'] == 'Paused')
                self.assertFalse(manager.snapshot()[0]['resumable'])
                manager.resume(job_id)
                self.wait_for(lambda: manager.snapshot()[0]['status'] in ('Complete', 'Error'))
                job = manager.snapshot()[0]
                self.assertEqual(job['status'], 'Complete', job['error'])
                self.assertEqual(Path(job['target']).read_bytes(), DATA)
            finally:
                self.stop(manager)
