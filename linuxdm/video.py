"""Streaming downloads via yt-dlp, isolated from the desktop UI process."""
import errno
import json
import os
import queue
import threading
import shutil
import signal
import subprocess
import time
from collections import deque
from pathlib import Path


def executable(name):
    bundled = Path(__file__).resolve().parent.parent / 'bin' / (name + '.exe' if os.name == 'nt' else name)
    if bundled.is_file():
        return str(bundled)
    found = shutil.which(name)
    if found:
        return found
    for folder in (Path.home() / '.local/bin', Path.home() / '.deno/bin', Path('/usr/local/bin')):
        candidate = folder / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def video_command(job, work):
    program = executable('yt-dlp')
    if not program:
        raise ValueError('Video downloads need yt-dlp. Install yt-dlp and FFmpeg, then retry.')
    if not executable('ffmpeg'):
        raise ValueError('Video downloads need FFmpeg to combine audio and video. Install it, then retry.')
    quality = job.get('quality', 'best')
    formats = 'bv*+ba/b' if quality == 'best' else f'bv*[height<={quality}]+ba/b[height<={quality}]'
    command = [program, '--ignore-config', '--no-plugin-dirs', '--no-playlist', '--playlist-items', '1',
               '--no-simulate', '--newline', '--progress', '--progress-delta', '0.3',
               '--progress-template', 'download:LINUXDM_PROGRESS:%(progress)j',
               '--progress-template', 'postprocess:LINUXDM_POST:%(progress.status)s',
               '--print', 'after_move:LINUXDM_FILE:%(filepath)j',
               '--print', 'before_dl:LINUXDM_TITLE:%(title)j',
               '--no-overwrites', '--continue', '--socket-timeout', '20',
               '--retries', '3', '--fragment-retries', '3',
               '--concurrent-fragments', str(job['connections']),
               '--ffmpeg-location', executable('ffmpeg'),
               '--paths', str(work), '--output', 'media.%(ext)s', '--format', formats]
    runtime = executable('deno') or executable('node')
    if runtime:
        name = 'deno' if Path(runtime).stem == 'deno' else 'node'
        command += ['--js-runtimes', f'{name}:{runtime}']
    return command + ['--', job['url']]


def download_video(manager, job, stop, work):
    command = video_command(job, work)
    with manager.lock:
        job.update(video_phase='Reading video information…', speed=0)
    flags = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
    process = subprocess.Popen(command, cwd=work, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               **flags)
    lines = deque(maxlen=8)
    streams = {}
    final_file = None
    buffer = b''
    stop_time = None

    def handle(line):
        nonlocal final_file
        if line.startswith('LINUXDM_PROGRESS:'):
            try:
                progress = json.loads(line.split(':', 1)[1])
                done = int(progress.get('downloaded_bytes') or 0)
                total = int(progress.get('total_bytes') or progress.get('total_bytes_estimate') or 0)
                streams[progress.get('filename', 'stream')] = (done, total)
                with manager.lock:
                    job.update(done=sum(p[0] for p in streams.values()),
                               total=sum(p[1] for p in streams.values()),
                               speed=float(progress.get('speed') or 0) if job['status'] == 'Downloading' else 0,
                               video_phase='Downloading video / audio streams')
            except (ValueError, TypeError, AttributeError):
                pass
        elif line.startswith('LINUXDM_POST:'):
            with manager.lock:
                job.update(video_phase='Combining video and audio…', speed=0)
        elif line.startswith('LINUXDM_FILE:'):
            try:
                final_file = Path(json.loads(line.split(':', 1)[1])).resolve()
            except (ValueError, TypeError):
                pass
        elif line.startswith('LINUXDM_TITLE:'):
            try:
                title = json.loads(line.split(':', 1)[1])
                if isinstance(title, str):
                    with manager.lock:
                        job['video_title'] = title
            except ValueError:
                pass
        elif line:
            lines.append(line)

    def terminate(sig):
        try:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass

    output = queue.Queue()
    def read_output():
        try:
            while chunk := process.stdout.read1(65536):
                output.put(chunk)
        finally:
            output.put(None)
    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    try:
        eof = False
        while not eof or process.poll() is None:
            if stop.is_set():
                if stop_time is None:
                    terminate(signal.SIGTERM)
                    stop_time = time.monotonic()
                elif time.monotonic() - stop_time > 3:
                    terminate(getattr(signal, 'SIGKILL', signal.SIGTERM))
            try:
                chunk = output.get(timeout=.1)
            except queue.Empty:
                continue
            if chunk is None:
                eof = True
                continue
            buffer += chunk
            while b'\n' in buffer:
                raw, buffer = buffer.split(b'\n', 1)
                handle(raw.decode('utf-8', errors='replace').strip())
        if buffer:
            handle(buffer.decode('utf-8', errors='replace').strip())
        code = process.wait()
    finally:
        if process.poll() is None:
            terminate(getattr(signal, 'SIGKILL', signal.SIGTERM))
            process.wait()
        process.stdout.close()
    if stop.is_set():
        return
    if code:
        raise ValueError('\n'.join(lines) or f'Video download failed (yt-dlp exit {code}).')
    if final_file is None or not final_file.is_relative_to(work.resolve()) or not final_file.is_file():
        raise ValueError('The video downloader did not produce a completed file.')
    with manager.lock:
        if stop.is_set():
            return
        job.update(status='Finishing', speed=0)
        requested = Path(job['target'])
        # The actual container is determined by the downloaded streams.
        base = requested.stem if requested.suffix.lower() in ('.mp4', '.mkv', '.webm', '.mov', '.m4v') else requested.name
        if job.get('video_name_auto') and job.get('video_title'):
            base = job['video_title']
        job['target'] = manager._target(job['url'], requested.parent, base + final_file.suffix, exclude=job['id'])
        target = Path(job['target'])
    try:
        os.link(final_file, target)  # Atomic and refuses to overwrite an existing file.
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        created = False
        try:
            with target.open('xb') as output, final_file.open('rb') as source:
                created = True
                shutil.copyfileobj(source, output, length=1024 * 1024)
        except Exception:
            if created:
                target.unlink(missing_ok=True)
            raise
    amount = target.stat().st_size
    with manager.lock:
        job.update(status='Complete', total=amount, done=amount, speed=0, video_phase='Video saved')
    # Final output has its own directory entry; removing the cache cannot delete it.
    try:
        shutil.rmtree(work)
    except OSError:
        pass  # The completed output remains valid; Remove can retry cache cleanup.
