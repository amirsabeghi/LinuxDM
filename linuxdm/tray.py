"""Linux panel indicator, with GTK events dispatched by Tk's main thread."""
from pathlib import Path


def load_backend():
    import gi
    gi.require_version('Gtk', '3.0')
    try:
        gi.require_version('AyatanaAppIndicator3', '0.1')
        from gi.repository import AyatanaAppIndicator3 as Indicator
    except ValueError:
        gi.require_version('AppIndicator3', '0.1')
        from gi.repository import AppIndicator3 as Indicator
    from gi.repository import Gtk, GLib
    if not Gtk.init_check()[0]:
        raise RuntimeError('The tray could not connect to the desktop display.')
    return Gtk, GLib, Indicator


class TrayIcon:
    def __init__(self, root, show, quit_app):
        self.root = root
        self.timer = None
        self.closed = False
        self.indicator = None
        self.error = None
        try:
            Gtk, GLib, self.backend = load_backend()
        except (ImportError, ValueError, RuntimeError) as error:
            self.error = str(error)
            return
        self.context = GLib.MainContext.default()
        icon = Path(__file__).resolve().parent.parent / 'chrome-extension/icon48.png'
        self.indicator = self.backend.Indicator.new('linuxdm', str(icon),
                                                   self.backend.IndicatorCategory.APPLICATION_STATUS)
        self.indicator.set_title('LinuxDM — Running')
        self.menu = Gtk.Menu()
        status = Gtk.MenuItem(label='LinuxDM is running')
        status.set_sensitive(False)
        self.menu.append(status)
        self.open_item = Gtk.MenuItem(label='Open LinuxDM')
        self.open_item.connect('activate', lambda *_: show())
        self.menu.append(self.open_item)
        self.menu.append(Gtk.SeparatorMenuItem())
        self.quit_item = Gtk.MenuItem(label='Quit LinuxDM')
        self.quit_item.connect('activate', lambda *_: quit_app())
        self.menu.append(self.quit_item)
        self.menu.show_all()
        self.indicator.set_menu(self.menu)
        self.indicator.set_secondary_activate_target(self.open_item)
        self.indicator.set_status(self.backend.IndicatorStatus.ACTIVE)
        self._pump()

    def _pump(self):
        self.timer = None
        # Bound work and never block Tk, including when the window is hidden.
        for _ in range(20):
            if self.closed or not self.context.pending():
                break
            self.context.iteration(False)
        if not self.closed:
            self.timer = self.root.after(100, self._pump)

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.timer is not None:
            self.root.after_cancel(self.timer)
            self.timer = None
        if self.indicator is not None:
            self.indicator.set_status(self.backend.IndicatorStatus.PASSIVE)
            self.menu.destroy()
