import os
import unittest
from unittest.mock import MagicMock, patch
from linuxdm.tray import TrayIcon


class TrayTest(unittest.TestCase):
    def test_missing_optional_backend_does_not_break_download_app(self):
        root = MagicMock()
        with patch('linuxdm.tray.load_backend', side_effect=ImportError('Missing indicator library')):
            tray = TrayIcon(root, lambda: None, lambda: None)
        self.assertIn('Missing', tray.error)
        root.after.assert_not_called()
        tray.close()
        tray.close()

    @unittest.skipUnless(os.environ.get('LINUXDM_TEST_GUI') == '1', 'requires an opted-in desktop session')
    def test_real_indicator_actions_and_shutdown_while_window_is_hidden(self):
        import tkinter as tk
        import time
        root = tk.Tk()
        root.withdraw()
        actions = []
        tray = None
        try:
            def show():
                actions.append('show')
                root.deiconify()

            def quit_app():
                actions.append('quit')
                tray.close()

            tray = TrayIcon(root, show, quit_app)
            self.assertIsNone(tray.error)
            self.assertEqual(tray.indicator.get_status(), tray.backend.IndicatorStatus.ACTIVE)
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                root.update()
                time.sleep(.01)
            self.assertTrue(tray.indicator.get_property('connected'), 'Desktop tray host did not accept the indicator')
            self.assertEqual(root.state(), 'withdrawn')
            tray.open_item.activate()
            root.update()
            self.assertEqual(root.state(), 'normal')
            self.assertEqual(actions, ['show'])
            tray.quit_item.activate()
            self.assertEqual(actions, ['show', 'quit'])
            self.assertTrue(tray.closed)
            self.assertIsNone(tray.timer)
            self.assertEqual(tray.indicator.get_status(), tray.backend.IndicatorStatus.PASSIVE)
        finally:
            if tray:
                tray.close()
            root.destroy()
