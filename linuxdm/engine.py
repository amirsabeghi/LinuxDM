import concurrent.futures
import json
import re
import shutil
import threading
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from .video import download_video
from .platform_support import state_dir as default_state_dir


class DownloadManager:
    def __init__(self, state_dir=None):
        self.root = Path(state_dir or default_state_dir())
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.jobs = []
        self.stops = {}
        self.active = set()
        self.closed = False
        self.parallel = 2
        self.last_queue = None
        self.queues = [{'id': 'default', 'name': 'Default', 'parallel': 2, 'paused': False}]
        try:
            settings = json.loads((self.root / 'queues.json').read_text())
            self.queues = settings['queues']
            self.parallel = settings.get('parallel', 2)
            if not any(q['id'] == 'default' for q in self.queues):
                self.queues.insert(0, {'id': 'default', 'name': 'Default', 'parallel': 2, 'paused': False})
        except (OSError, ValueError, KeyError):
            pass
        try:
            self.jobs = json.loads((self.root / 'queue.json').read_text())
            for job in list(self.jobs):
                if job.get('queue_id') not in {q['id'] for q in self.queues}:
                    job['queue_id'] = 'default'
                job.setdefault('kind', 'file')
                if job.get('remove_requested'):
                    self._forget_job(job)
                    continue
                if job['status'] in ('Downloading', 'Queued', 'Pausing', 'Resuming', 'Finishing'):
                    job['status'] = 'Paused'
                job['speed'] = 0
            self._save()
        except (OSError, ValueError):
            pass
        threading.Thread(target=self._schedule, daemon=True).start()

    def _save(self):
        with self.lock:
            temp = self.root / 'queue.tmp'
            temp.write_text(json.dumps(self.jobs, indent=2))
            temp.replace(self.root / 'queue.json')
            settings = self.root / 'queues.tmp'
            settings.write_text(json.dumps({'queues': self.queues, 'parallel': self.parallel}, indent=2))
            settings.replace(self.root / 'queues.json')

    def queue_snapshot(self):
        with self.lock:
            return [dict(q) for q in self.queues]

    def _queue(self, queue_id):
        queue = next((q for q in self.queues if q['id'] == queue_id), None)
        if queue is None:
            raise ValueError('Choose an existing queue.')
        return queue

    def save_queue(self, name, parallel=2, queue_id=None):
        name = name.strip()
        if not name or len(name) > 48 or any(ord(c) < 32 for c in name):
            raise ValueError('Use a queue name of 1–48 characters.')
        if not 1 <= int(parallel) <= 8:
            raise ValueError('Choose 1–8 simultaneous downloads for this queue.')
        with self.lock:
            if any(q['name'].casefold() == name.casefold() and q['id'] != queue_id for q in self.queues):
                raise ValueError('A queue with this name already exists.')
            if queue_id:
                queue = self._queue(queue_id)
                queue.update(name=name, parallel=int(parallel))
            else:
                queue_id = uuid.uuid4().hex
                self.queues.append(dict(id=queue_id, name=name, parallel=int(parallel), paused=False))
            self._save()
            return queue_id

    def pause_queue(self, queue_id, paused=True):
        with self.lock:
            self._queue(queue_id)['paused'] = paused
            for job in self.jobs:
                if job['queue_id'] != queue_id:
                    continue
                if paused and job['status'] in ('Downloading', 'Resuming'):
                    self.pause(job['id'])
                    job['queue_hold'] = True
                elif not paused and job.pop('queue_hold', False):
                    self.resume(job['id'])
            self._save()

    def move_to_queue(self, job_id, queue_id):
        with self.lock:
            queue = self._queue(queue_id)
            job = next((j for j in self.jobs if j['id'] == job_id), None)
            if not job:
                return
            if job['status'] == 'Removing':
                job['queue_id'] = queue_id
                self._save()
                return
            was_held = job.pop('queue_hold', False)
            moving_transfer = job['status'] in ('Downloading', 'Resuming')
            job['queue_id'] = queue_id
            if moving_transfer:
                self.pause(job_id)
            if moving_transfer or was_held:
                if queue['paused']:
                    job['queue_hold'] = True
                else:
                    self.resume(job_id)
            self._save()

    def delete_queue(self, queue_id):
        if queue_id == 'default':
            raise ValueError('The default queue cannot be deleted.')
        with self.lock:
            self._queue(queue_id)
            for job in list(self.jobs):
                if job['queue_id'] == queue_id:
                    self.move_to_queue(job['id'], 'default')
            self.queues = [q for q in self.queues if q['id'] != queue_id]
            self._save()

    def set_parallel(self, count):
        with self.lock:
            self.parallel = max(1, min(8, int(count)))
            self._save()

    def _target(self, url, directory, filename=None, exclude=None):
        parsed = urllib.parse.urlsplit(url)
        name = Path((filename or urllib.parse.unquote(parsed.path)).replace('\\', '/')).name or 'download'
        name = re.sub(r'[^\w.() -]', '_', name).strip('.') or 'download'
        name = name.encode('utf-8')[:220].decode('utf-8', errors='ignore') or 'download'
        directory = Path(directory).expanduser().resolve()
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / name
        count = 1
        reserved = {j['target'] for j in self.jobs if j['id'] != exclude}
        while target.exists() or str(target) in reserved:
            target = directory / f'{Path(name).stem} ({count}){Path(name).suffix}'
            count += 1
        return str(target)

    def add(self, url, directory, connections=4, request_id=None, filename=None,
            awaiting_confirmation=False, queue_id='default', kind='file', quality='best'):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            raise ValueError('Enter a valid HTTP or HTTPS URL.')
        with self.lock:
            self._queue(queue_id)
            if kind not in ('file', 'video') or quality not in ('best', '1080', '720', '480'):
                raise ValueError('Invalid download type or video quality.')
            if request_id and any(j['id'] == request_id for j in self.jobs):
                return request_id
            target = self._target(url, directory, filename or ('Video' if kind == 'video' else None))
            job = dict(id=request_id or uuid.uuid4().hex, url=url, target=target,
                       connections=max(1, min(16, int(connections))),
                       status='Ready' if awaiting_confirmation else 'Queued',
                       needs_confirmation=awaiting_confirmation, total=0, done=0, speed=0, error='')
            job.update(queue_id=queue_id, kind=kind, quality=quality,
                       video_name_auto=kind == 'video' and not filename)
            self.jobs.append(job)
            self._save()
        return job['id']

    def confirm(self, job_id, directory, filename, connections, start=True, queue_id=None, quality='best'):
        with self.lock:
            job = next((j for j in self.jobs if j['id'] == job_id), None)
            if not job or job['status'] != 'Ready' or self.closed:
                raise ValueError('This download is no longer waiting for confirmation.')
            count = int(connections)
            self._queue(queue_id or job['queue_id'])
            if quality not in ('best', '1080', '720', '480'):
                raise ValueError('Choose a supported video quality.')
            if not 1 <= count <= 16 or not filename.strip() or not str(directory).strip():
                raise ValueError('Choose a filename, destination, and 1–16 connections.')
            target = self._target(job['url'], directory, filename, exclude=job_id)
            if filename != Path(job['target']).name:
                job['video_name_auto'] = False
            job.update(target=target, connections=count, needs_confirmation=False,
                       status='Queued' if start else 'Paused', queue_id=queue_id or job['queue_id'], quality=quality)
            self._save()

    def defer(self, job_id):
        with self.lock:
            for job in self.jobs:
                if job['id'] == job_id and job['status'] == 'Ready':
                    job.update(status='Paused', needs_confirmation=False)
            self._save()

    def _forget_job(self, job):
        # Never remove the destination file; only this job's private cache.
        try:
            if re.fullmatch(r'[0-9a-f]{32}', job['id']):
                cache = self.root / job['id']
                if cache.exists():
                    shutil.rmtree(cache)
        except OSError as exc:
            job.update(status='Error', error=f'Could not remove temporary data: {exc}',
                       remove_requested=False)
            return
        self.jobs = [j for j in self.jobs if j['id'] != job['id']]

    def remove(self, job_id):
        with self.lock:
            job = next((j for j in self.jobs if j['id'] == job_id), None)
            if job is None:
                return
            job.update(status='Removing', remove_requested=True, needs_confirmation=False, speed=0)
            if job_id in self.active:
                self.stops[job_id].set()
            else:
                self._forget_job(job)
            self._save()

    def clear_completed(self, queue_id=None):
        with self.lock:
            for job in list(self.jobs):
                if job['status'] == 'Complete' and (queue_id is None or job['queue_id'] == queue_id):
                    self.remove(job['id'])

    def snapshot(self):
        with self.lock:
            return [dict(j) for j in self.jobs]

    def pause(self, job_id):
        with self.lock:
            for j in self.jobs:
                if j['id'] == job_id:
                    j.pop('queue_hold', None)
                if j['id'] == job_id and j['status'] in ('Queued', 'Downloading', 'Resuming'):
                    j['status'] = 'Pausing' if job_id in self.active else 'Paused'
                    j['speed'] = 0
                    if job_id in self.stops:
                        self.stops[job_id].set()
            self._save()

    def resume(self, job_id):
        with self.lock:
            for j in self.jobs:
                if j['id'] == job_id and j['status'] in ('Paused', 'Pausing', 'Error') and not self.closed:
                    j.update(status='Resuming' if job_id in self.active else 'Queued', error='')
            self._save()

    def close(self):
        with self.lock:
            self.closed = True
            for j in self.jobs:
                held = j.get('queue_hold', False)
                self.pause(j['id'])
                if held:
                    j['queue_hold'] = True
            self._save()

    def _schedule(self):
        while not self.closed:
            with self.lock:
                if self.closed:
                    return
                while len(self.active) < self.parallel:
                    # Give runnable queues turns while retaining FIFO inside each queue.
                    ids = [q['id'] for q in self.queues]
                    start = (ids.index(self.last_queue) + 1) % len(ids) if self.last_queue in ids else 0
                    for queue in self.queues[start:] + self.queues[:start]:
                        count = sum(j['id'] in self.active and j['queue_id'] == queue['id'] for j in self.jobs)
                        if queue['paused'] or count >= queue['parallel']:
                            continue
                        job = next((j for j in self.jobs if j['queue_id'] == queue['id']
                                    and j['status'] == 'Queued' and j['id'] not in self.active), None)
                        if not job:
                            continue
                        self.active.add(job['id'])
                        stop = self.stops[job['id']] = threading.Event()
                        job['status'] = 'Downloading'
                        self.last_queue = queue['id']
                        threading.Thread(target=self._run, args=(job, stop), daemon=True).start()
                        break
                    else:
                        break
            time.sleep(.2)

    def _request(self, url, headers=None):
        return urllib.request.urlopen(urllib.request.Request(url, headers={
            'User-Agent': 'LinuxDM/0.1', 'Accept-Encoding': 'identity', **(headers or {})}), timeout=20)

    def _run(self, job, stop):
        work = self.root / job['id']
        try:
            work.mkdir(exist_ok=True)
            if stop.is_set():
                return
            if job.get('kind') == 'video':
                download_video(self, job, stop, work)
                return
            with self._request(job['url'], {'Range': 'bytes=0-0'}) as response:
                match = re.fullmatch(r'bytes 0-0/(\d+)', response.headers.get('Content-Range', ''))
                ranged = response.status == 206 and match is not None
                total = int(match[1]) if ranged else int(response.headers.get('Content-Length', 0))
                etag = response.headers.get('ETag', '')
                validator = (etag if not etag.startswith('W/') else None) or response.headers.get('Last-Modified')
            if stop.is_set():
                return
            count = min(job['connections'], max(1, total // (256 * 1024))) if ranged else 1
            metadata = dict(total=total, count=count, validator=validator, ranged=ranged)
            meta_file = work / 'metadata.json'
            previous = json.loads(meta_file.read_text()) if meta_file.exists() else None
            if previous != metadata or not ranged or not validator:
                for part in work.glob('*.part'):
                    part.unlink()
            meta_file.write_text(json.dumps(metadata))
            with self.lock:
                job.update(total=total, done=sum(p.stat().st_size for p in work.glob('*.part')),
                           speed=0, resumable=bool(ranged and validator), used_connections=count)
            started = time.monotonic()
            initial = job['done']

            def transfer(index):
                if stop.is_set():
                    return
                start = total * index // count
                end = total * (index + 1) // count - 1
                part = work / f'{index}.part'
                offset = part.stat().st_size if part.exists() else 0
                expected = end - start + 1
                if ranged and offset == expected:
                    return
                if ranged and offset > expected:
                    raise ValueError('Invalid partial file; remove the job cache before retrying.')
                headers = {'Range': f'bytes={start + offset}-{end}'} if ranged else {}
                if ranged and validator:
                    headers['If-Range'] = validator
                with self._request(job['url'], headers) as response:
                    if ranged and (response.status != 206 or response.headers.get('Content-Range') != f'bytes {start + offset}-{end}/{total}'):
                        raise ValueError('The server changed the file or rejected the requested range. Retry to refresh it.')
                    received = offset
                    with part.open('ab' if ranged else 'wb') as out:
                        while not stop.is_set():
                            chunk = response.read1(65536)
                            if not chunk:
                                break
                            if ranged and received + len(chunk) > expected:
                                raise ValueError('Server returned more data than requested.')
                            out.write(chunk)
                            received += len(chunk)
                            with self.lock:
                                job['done'] += len(chunk)
                                if job['status'] == 'Downloading':
                                    job['speed'] = (job['done'] - initial) / max(.1, time.monotonic() - started)
                    if not stop.is_set() and ((ranged and received != expected) or (not ranged and total and received != total)):
                        raise IOError('Connection ended before the download completed. Resume to retry.')

            with concurrent.futures.ThreadPoolExecutor(max_workers=count) as pool:
                futures = [pool.submit(transfer, i) for i in range(count)]
                try:
                    for f in concurrent.futures.as_completed(futures):
                        f.result()
                except Exception:
                    stop.set()
                    raise
            with self.lock:
                if stop.is_set():
                    return
                job.update(status='Finishing', speed=0)
            target = Path(job['target'])
            try:
                with target.open('xb') as out:
                    for i in range(count):
                        with (work / f'{i}.part').open('rb') as part:
                            while chunk := part.read(1024 * 1024):
                                out.write(chunk)
            except FileExistsError:
                raise ValueError('Destination now exists. Move it before retrying.')
            except Exception:
                target.unlink(missing_ok=True)
                raise
            with self.lock:
                job.update(status='Complete', speed=0, total=job['done'])
            for part in work.glob('*.part'):
                part.unlink()
        except Exception as exc:
            with self.lock:
                if job['status'] not in ('Paused', 'Pausing', 'Resuming', 'Removing'):
                    job.update(status='Error', error=str(exc))
        finally:
            with self.lock:
                job['speed'] = 0
                self.active.discard(job['id'])
                self.stops.pop(job['id'], None)
                if job['status'] == 'Pausing':
                    job['status'] = 'Paused'
                elif job['status'] == 'Resuming':
                    job['status'] = 'Paused' if self.closed else 'Queued'
                if job.get('remove_requested'):
                    self._forget_job(job)
                self._save()
