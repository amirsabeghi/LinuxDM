"""Windows tray callbacks are queued back to Tk's main thread."""
import queue
import threading
from pathlib import Path


class TrayIcon:
    def __init__(self, root, show, quit_app):
        self.root, self.error, self.timer = root, None, None
        self.closed = False
        self.actions = queue.Queue()
        self.icon = None
        try:
            import pystray
            from PIL import Image
            image = Image.open(Path(__file__).resolve().parent.parent / 'chrome-extension/icon48.png')
            self.icon = pystray.Icon('LinuxDM', image, 'LinuxDM — Running', pystray.Menu(
                pystray.MenuItem('Open LinuxDM', lambda *_: self.actions.put(show), default=True),
                pystray.MenuItem('Quit LinuxDM', lambda *_: self.actions.put(quit_app))))
            threading.Thread(target=self.icon.run, daemon=True).start()
            self._pump()
        except ImportError as error:
            self.error = str(error)

    def _pump(self):
        self.timer = None
        while not self.closed:
            try:
                self.actions.get_nowait()()
            except queue.Empty:
                break
        if not self.closed:
            self.timer = self.root.after(100, self._pump)

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.timer:
            self.root.after_cancel(self.timer)
        if self.icon:
            self.icon.stop()
