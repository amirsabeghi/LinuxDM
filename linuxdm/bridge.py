"""Durable Chrome-to-desktop handoff; browser helpers never edit queue.json."""
from .platform_support import lock_file, state_dir
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import uuid
import urllib.request
from contextlib import contextmanager
from pathlib import Path

HOST_NAME = 'io.linuxdm.bridge'


@contextmanager
def inbox_lock(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / 'inbox.lock').open('a+b') as lock:
        lock_file(lock)
        yield


class AppInstance:
    def __init__(self, root=None):
        self.root = Path(root) if root else state_dir()
        self.acquired = False
        self.file = None

    def __enter__(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.file = (self.root / 'app.lock').open('a+b')
        try:
            lock_file(self.file, blocking=False)
            self.acquired = True
        except BlockingIOError:
            pass
        return self

    def __exit__(self, *_):
        self.file.close()
        self.acquired = False


def validate_url(url):
    if not isinstance(url, str) or len(url) > 16384 or any(ord(c) < 32 for c in url):
        raise ValueError('Enter a valid HTTP or HTTPS download link.')
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise ValueError('Only HTTP and HTTPS download links are supported.')
    return url


def write_json(path, value):
    temp = path.with_name(f'{path.stem}-{uuid.uuid4().hex}.tmp')
    try:
        with temp.open('x') as out:
            os.chmod(temp, 0o600)
            json.dump(value, out)
            out.flush()
            os.fsync(out.fileno())
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def enqueue(url, root=None, kind='file', title=''):
    url = validate_url(url)
    if kind not in ('file', 'video') or not isinstance(title, str) or len(title) > 512:
        raise ValueError('Invalid download type or title.')
    root = Path(root) if root else state_dir()
    inbox = root / 'inbox'
    inbox.mkdir(parents=True, exist_ok=True, mode=0o700)
    request_id = uuid.uuid4().hex
    write_json(inbox / f'{request_id}.json', {'url': url, 'created_ns': time.time_ns(),
                                          'kind': kind, 'filename': title if kind == 'video' else None})
    return request_id


def drain_inbox(manager, directory, connections, awaiting_confirmation=False):
    # Capture timeouts and UI acceptance must agree on who owns the download.
    with inbox_lock(manager.root):
        return _drain_inbox(manager, directory, connections, awaiting_confirmation)


def _drain_inbox(manager, directory, connections, awaiting_confirmation):
    inbox = manager.root / 'inbox'
    imported = []
    # Bound work per UI refresh so a burst of links does not freeze the window.
    def arrival_order(path):
        # Some filesystems give rapid arrivals identical modification times.
        fallback = path.stat().st_mtime_ns
        try:
            created = json.loads(path.read_text()).get('created_ns', fallback)
            return (created if isinstance(created, int) else fallback, path.name)
        except (OSError, ValueError, AttributeError):
            return (fallback, path.name)

    for path in sorted(inbox.glob('*.json'), key=arrival_order)[:20]:
        if not re.fullmatch(r'[0-9a-f]{32}', path.stem):
            continue
        try:
            request = json.loads(path.read_text())
            if request.get('expires', float('inf')) < time.time():
                raise ValueError('Handoff timed out. Continue downloading in Chrome.')
            url = validate_url(request.get('url'))
            destination = directory(url, request.get('filename'), request.get('kind', 'file')) if callable(directory) else directory
            job_id = manager.add(url, destination, connections, request_id=path.stem,
                                 filename=request.get('filename'),
                                 awaiting_confirmation=awaiting_confirmation,
                                 kind=request.get('kind', 'file'))
            result = {'ok': True, 'message': 'Received by LinuxDM. Choose Start download in its dialog.'
                      if awaiting_confirmation else 'Added to the LinuxDM queue.'}
            imported.append(job_id)
        except (OSError, ValueError, AttributeError, TypeError) as exc:
            result = {'ok': False, 'message': str(exc)}
        # Retain the request if acknowledging fails; the request ID prevents duplicates.
        try:
            write_json(path.with_suffix('.result'), result)
            path.unlink()
        except OSError:
            pass
    # A browser may close before consuming its acknowledgement.
    for path in inbox.glob('*.result'):
        try:
            if time.time() - path.stat().st_mtime > 86400:
                path.unlink()
        except OSError:
            pass
    return imported


def check_capture_id(request_id):
    if not isinstance(request_id, str) or not re.fullmatch(r'[0-9a-f]{32}', request_id):
        raise ValueError('Invalid capture request ID.')


def capture_outcome(root, request_id):
    """Read while holding inbox_lock. Queue membership survives lost receipts."""
    queue_path = root / 'queue.json'
    if queue_path.exists():
        jobs = json.loads(queue_path.read_text())
        if any(job['id'] == request_id for job in jobs):
            return {'ok': True, 'message': 'Added to the LinuxDM queue.'}
    result_path = root / 'inbox' / f'{request_id}.result'
    if result_path.exists():
        return json.loads(result_path.read_text())
    return None


def settle_capture(request_id, root=None):
    """Resolve an uncertain handoff, cancelling it if the app has not accepted it."""
    check_capture_id(request_id)
    root = Path(root) if root else state_dir()
    with inbox_lock(root):
        result = capture_outcome(root, request_id)
        if result is not None:
            return result
        inbox = root / 'inbox'
        inbox.mkdir(exist_ok=True, mode=0o700)
        (inbox / f'{request_id}.json').unlink(missing_ok=True)
        result = {'ok': False, 'message': 'LinuxDM did not accept the handoff. Continue in Chrome.'}
        # A delayed native process cannot recreate a request after Chrome resumes.
        write_json(inbox / f'{request_id}.result', result)
        return result


def probe_capture(url, mime):
    """Check that a normal GET works before taking a browser download."""
    request = urllib.request.Request(url, headers={
        'Range': 'bytes=0-0', 'Accept-Encoding': 'identity', 'User-Agent': 'LinuxDM/0.1'})
    with urllib.request.urlopen(request, timeout=5) as response:
        content_type = response.headers.get_content_type()
        if content_type == 'text/html' and mime != 'text/html':
            raise ValueError('This download requires the browser session. Continue in Chrome.')


def submit_capture(url, request_id, filename='', mime='', root=None, launch=None,
                   timeout=8, probe=probe_capture):
    check_capture_id(request_id)
    url = validate_url(url)
    if not isinstance(filename, str) or len(filename) > 4096 or not isinstance(mime, str):
        raise ValueError('Invalid browser download metadata.')
    root = Path(root) if root else state_dir()
    with inbox_lock(root):
        existing = capture_outcome(root, request_id)
        if existing is not None:
            return existing
    try:
        probe(url, mime)
    except Exception:
        return settle_capture(request_id, root)
    with inbox_lock(root):
        existing = capture_outcome(root, request_id)
        if existing is not None:
            return existing
        inbox = root / 'inbox'
        inbox.mkdir(exist_ok=True, mode=0o700)
        write_json(inbox / f'{request_id}.json', {
            'url': url, 'filename': filename, 'expires': time.time() + timeout,
            'created_ns': time.time_ns()})
    with AppInstance(root) as instance:
        running = not instance.acquired
    if not running:
        try:
            (launch or launch_app)()
        except OSError:
            return settle_capture(request_id, root)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with inbox_lock(root):
            result = capture_outcome(root, request_id)
        if result is not None:
            return result
        time.sleep(.05)
    return settle_capture(request_id, root)


def launch_app():
    project = Path(__file__).resolve().parent.parent
    python = str(Path(sys.executable).with_name('pythonw.exe')) if os.name == 'nt' else sys.executable
    subprocess.Popen([python, str(project / 'launch.pyw')] if (project / 'launch.pyw').exists()
                     else [python, '-m', 'linuxdm'], cwd=project,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def submit(url, root=None, launch=launch_app, timeout=8, kind='file', title=''):
    root = Path(root) if root else state_dir()
    request_id = enqueue(url, root, kind=kind, title=title)
    with AppInstance(root) as instance:
        running = not instance.acquired
    if not running:
        try:
            launch()
        except OSError:
            return {'ok': True, 'pending': True,
                    'message': 'Link saved. Open LinuxDM to start the download.'}
    result_path = root / 'inbox' / f'{request_id}.result'
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = json.loads(result_path.read_text())
            result_path.unlink(missing_ok=True)
            return result
        except FileNotFoundError:
            time.sleep(.05)
    return {'ok': True, 'pending': True,
            'message': 'Link saved. Open or restart LinuxDM to add it to the queue.'}


def request_show(root=None):
    root = Path(root) if root else state_dir()
    with inbox_lock(root):
        write_json(root / 'show-window.json', {'show': True})


def consume_show(root):
    with inbox_lock(root):
        path = Path(root) / 'show-window.json'
        if not path.exists():
            return False
        path.unlink()
        return True
