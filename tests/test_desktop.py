import tempfile
import unittest
from pathlib import Path
from linuxdm.desktop_install import install
from linuxdm.bridge import consume_show, request_show


class DesktopIntegrationTest(unittest.TestCase):
    def test_application_menu_install_and_show_signal(self):
        with tempfile.TemporaryDirectory(prefix='linuxdm space ') as tmp:
            data = Path(tmp)
            desktop = install(data)
            self.assertTrue(desktop.is_file())
            self.assertIn('Name=LinuxDM', desktop.read_text())
            self.assertIn('Exec="', desktop.read_text())
            self.assertTrue((data / 'linuxdm/linuxdm').stat().st_mode & 0o100)
            self.assertTrue((data / 'icons/hicolor/128x128/apps/io.linuxdm.png').is_file())
            state = data / 'state'
            request_show(state)
            self.assertTrue(consume_show(state))
            self.assertFalse(consume_show(state))

    def test_background_launchers_and_opt_in_login_start(self):
        from linuxdm.desktop_install import set_autostart, autostart_enabled
        with tempfile.TemporaryDirectory(prefix='linuxdm startup ') as tmp:
            data, config = Path(tmp) / 'data', Path(tmp) / 'config'
            old = data / 'applications/io.linuxdm.background.desktop'
            old.parent.mkdir(parents=True)
            old.write_text('old extra launcher')
            desktop = install(data)
            self.assertIn('Actions=Background;', desktop.read_text())
            self.assertIn('--background', desktop.read_text())
            self.assertFalse(old.exists())
            self.assertEqual(len(list(desktop.parent.glob('*.desktop'))), 1)
            self.assertFalse(autostart_enabled(config))
            startup = set_autostart(True, config, data)
            self.assertTrue(autostart_enabled(config))
            self.assertIn('--background', startup.read_text())
            install(data)  # Reinstalling the launcher must not reset the login preference.
            self.assertTrue(autostart_enabled(config))
            set_autostart(False, config, data)
            self.assertFalse(autostart_enabled(config))

    def test_background_start_hides_root_before_building_window(self):
        from unittest.mock import patch, MagicMock
        from linuxdm.__main__ import main
        events = []
        root = MagicMock()
        root.withdraw.side_effect = lambda: events.append('hidden')
        with patch('sys.argv', ['linuxdm', '--background']), \
             patch('linuxdm.__main__.AppInstance') as instance, \
             patch('linuxdm.__main__.tk.Tk', return_value=root), \
             patch('linuxdm.__main__.DownloadManager'), \
             patch('linuxdm.__main__.TrayIcon'), \
             patch('linuxdm.__main__.DownloadApp', side_effect=lambda *_: (events.append('built'), MagicMock())[1]):
            instance.return_value.__enter__.return_value.acquired = True
            main()
        self.assertEqual(events, ['hidden', 'built'])
        root.mainloop.assert_called_once()

    def test_background_start_reuses_existing_process_without_showing_window(self):
        from unittest.mock import patch
        from linuxdm.__main__ import main
        with patch('sys.argv', ['linuxdm', '--background']), \
             patch('linuxdm.__main__.AppInstance') as instance, \
             patch('linuxdm.__main__.request_show') as show, \
             patch('linuxdm.__main__.tk.Tk') as create:
            instance.return_value.__enter__.return_value.acquired = False
            main()
            show.assert_not_called()
            create.assert_not_called()
