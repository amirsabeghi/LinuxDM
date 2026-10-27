import tempfile
import json
import unittest
from pathlib import Path
from linuxdm.engine import DownloadManager


class QueueTest(unittest.TestCase):
    def test_old_queue_file_moves_into_default_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = dict(id='a' * 32, url='https://example.invalid/file', target=str(root / 'file'),
                       connections=4, status='Paused', done=0, total=0, speed=0, error='')
            (root / 'queue.json').write_text(json.dumps([old]))
            manager = DownloadManager(root)
            try:
                self.assertEqual(manager.snapshot()[0]['queue_id'], 'default')
                self.assertEqual(manager.snapshot()[0]['kind'], 'file')
            finally:
                manager.close()

    def test_queue_pause_can_be_resumed_after_app_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = DownloadManager(Path(tmp) / 'state')
            manager.parallel = 0
            custom = manager.save_queue('Paused queue')
            manager.add('https://example.invalid/file', tmp, queue_id=custom)
            manager.pause_queue(custom)
            manager.jobs[0].update(status='Paused', queue_hold=True)
            manager.close()
            restored = DownloadManager(Path(tmp) / 'state')
            try:
                restored.pause_queue(custom, False)
                self.assertEqual(restored.snapshot()[0]['status'], 'Queued')
            finally:
                restored.close()

    def test_named_queues_persist_and_migrate_legacy_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'state'
            manager = DownloadManager(root)
            manager.parallel = 0
            work = manager.save_queue('Work files', 1)
            video = manager.save_queue('Videos', 3)
            job_id = manager.add('https://example.invalid/file.zip', tmp, queue_id=work)
            manager.pause_queue(work)
            manager.save_queue('Office files', 2, work)
            manager.close()
            restored = DownloadManager(root)
            try:
                self.assertEqual(restored.snapshot()[0]['queue_id'], work)
                q = next(q for q in restored.queue_snapshot() if q['id'] == work)
                self.assertEqual(q['name'], 'Office files')
                self.assertTrue(q['paused'])
                self.assertEqual(q['parallel'], 2)
                restored.move_to_queue(job_id, video)
                self.assertEqual(restored.snapshot()[0]['queue_id'], video)
                restored.delete_queue(video)
                self.assertEqual(restored.snapshot()[0]['queue_id'], 'default')
                with self.assertRaises(ValueError):
                    restored.delete_queue('default')
                with self.assertRaises(ValueError):
                    restored.save_queue('OFFICE FILES')
            finally:
                restored.close()

    def test_clear_completed_is_scoped_to_selected_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = DownloadManager(Path(tmp) / 'state')
            manager.parallel = 0
            try:
                custom = manager.save_queue('Archive', 1)
                first = manager.add('https://example.invalid/first.zip', tmp)
                second = manager.add('https://example.invalid/second.zip', tmp, queue_id=custom)
                for job in manager.jobs:
                    job['status'] = 'Complete'
                manager.clear_completed(custom)
                self.assertEqual([j['id'] for j in manager.snapshot()], [first])
                self.assertNotEqual(first, second)
            finally:
                manager.close()
