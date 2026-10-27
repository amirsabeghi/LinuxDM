import functools
import http.server
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from linuxdm.engine import DownloadManager


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass


class VideoTest(unittest.TestCase):
    def wait_for(self, condition, timeout=35):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if condition():
                return
            time.sleep(.03)
        self.fail('Timed out waiting for video download')

    def stop(self, manager):
        manager.close()
        self.wait_for(lambda: not manager.active, 8)

    @unittest.skipUnless(shutil.which('yt-dlp') and shutil.which('ffmpeg') and shutil.which('ffprobe'), 'requires yt-dlp and FFmpeg')
    def test_real_hls_stream_is_downloaded_and_muxed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'server'
            source.mkdir()
            subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
                            'color=c=yellow:s=160x90:r=10', '-f', 'lavfi', '-i',
                            'sine=frequency=440:sample_rate=44100', '-t', '3',
                            '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', '-g', '10',
                            '-c:a', 'aac', '-f', 'hls', '-hls_time', '1', '-hls_list_size', '0',
                            '-hls_segment_filename', str(source / 'part%02d.ts'), str(source / 'stream.m3u8')], check=True)
            server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(QuietHandler, directory=str(source)))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            manager = DownloadManager(root / 'state')
            try:
                out = root / 'downloads'
                out.mkdir()
                (out / 'Sample.mp4').write_bytes(b'keep existing file')
                manager.add(f'http://127.0.0.1:{server.server_port}/stream.m3u8', out,
                            kind='video', filename='Sample', connections=2)
                self.wait_for(lambda: manager.snapshot()[0]['status'] in ('Complete', 'Error'))
                job = manager.snapshot()[0]
                self.assertEqual(job['status'], 'Complete', job['error'])
                self.assertEqual((out / 'Sample.mp4').read_bytes(), b'keep existing file')
                self.assertGreater(Path(job['target']).stat().st_size, 1000)
                result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type',
                                         '-of', 'json', job['target']], capture_output=True, text=True, check=True)
                self.assertEqual({s['codec_type'] for s in json.loads(result.stdout)['streams']}, {'audio', 'video'})
            finally:
                self.stop(manager)
                server.shutdown()
                server.server_close()

    def test_video_pause_terminates_process_and_resume_keeps_partial_data(self):
        script = '''import json, pathlib, time
work = pathlib.Path.cwd()
part = work / 'media.part'
if not part.exists():
    part.write_bytes(b'partial')
    print('LINUXDM_PROGRESS:' + json.dumps({'filename': str(part), 'downloaded_bytes': 7, 'total_bytes': 14}), flush=True)
    while True: time.sleep(.1)
else:
    final = work / 'media.mp4'
    final.write_bytes(part.read_bytes() + b'complete')
    print('LINUXDM_FILE:' + json.dumps(str(final)), flush=True)
'''
        with tempfile.TemporaryDirectory() as tmp:
            manager = DownloadManager(Path(tmp) / 'state')
            try:
                with patch('linuxdm.video.video_command', return_value=[sys.executable, '-u', '-c', script]):
                    job_id = manager.add('https://example.invalid/video', tmp, kind='video')
                    self.wait_for(lambda: manager.snapshot()[0]['done'] == 7)
                    manager.pause(job_id)
                    self.wait_for(lambda: manager.snapshot()[0]['status'] == 'Paused')
                    self.assertTrue((manager.root / job_id / 'media.part').exists())
                    manager.resume(job_id)
                    self.wait_for(lambda: manager.snapshot()[0]['status'] in ('Complete', 'Error'))
                    job = manager.snapshot()[0]
                    self.assertEqual(job['status'], 'Complete', job['error'])
                    self.assertEqual(Path(job['target']).read_bytes(), b'partialcomplete')
            finally:
                self.stop(manager)
