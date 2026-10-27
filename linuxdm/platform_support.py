"""Small operating-system adapters shared by the desktop and native host."""
import os
import time
from pathlib import Path

WINDOWS = os.name == 'nt'


def state_dir():
    if WINDOWS:
        return Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'LinuxDM'
    return Path.home() / '.local/share/linuxdm'


def lock_file(file, blocking=True):
    if not WINDOWS:
        import fcntl
        fcntl.flock(file, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        return
    import msvcrt
    file.seek(0, 2)
    if file.tell() == 0:
        file.write(b'0')
        file.flush()
    while True:
        file.seek(0)
        try:
            msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            return
        except OSError as error:
            if not blocking:
                raise BlockingIOError(str(error)) from error
            time.sleep(.05)
