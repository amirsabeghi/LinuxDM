"""Opt-in desktop checks: LINUXDM_TEST_GUI=1 python3 -m unittest discover -s tests -v."""
import os
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from pathlib import Path

from linuxdm.__main__ import DownloadApp
from linuxdm.engine import DownloadManager
from linuxdm.bridge import enqueue


@unittest.skipUnless(os.environ.get('LINUXDM_TEST_GUI') == '1', 'requires an opted-in desktop session')
class DesktopTest(unittest.TestCase):
    def refresh_now(self):
        self.root.after_cancel(self.app.refresh_timer)
        self.app.refresh()
        self.root.update()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.manager = DownloadManager(Path(self.temp.name) / 'state')
        self.manager.parallel = 0  # Exercise queue controls without making external requests.
        self.root = tk.Tk()
        self.app = DownloadApp(self.root, self.manager)
        self.app.directory = str(Path(self.temp.name) / 'Downloads')
        self.root.update()

    def tearDown(self):
        self.app.close()
        self.temp.cleanup()

    def test_hide_preserves_queue_and_launcher_request_restores_window(self):
        from linuxdm.bridge import request_show
        job = self.manager.add('https://example.invalid/a.zip', self.temp.name)
        self.app.hide()
        self.root.update()
        self.assertEqual(self.root.state(), 'withdrawn')
        self.assertFalse(self.manager.closed)
        self.assertEqual(self.manager.snapshot()[0]['status'], 'Queued')
        request_show(self.manager.root)
        self.refresh_now()
        self.assertEqual(self.root.state(), 'normal')
        self.assertEqual(self.manager.snapshot()[0]['id'], job)

    def test_context_menu_selects_clicked_row_and_directory_opens_without_shell(self):
        first = self.manager.add('https://example.invalid/a.zip', self.temp.name)
        second = self.manager.add('https://example.invalid/b.zip', self.temp.name)
        self.refresh_now()
        self.app.tree.selection_set(first)
        _, y, _, height = self.app.tree.bbox(second)
        with patch('tkinter.Menu.tk_popup'), patch('tkinter.Menu.grab_release'):
            self.app.context_menu(SimpleNamespace(num=3, y=y + height // 2, x_root=50, y_root=50))
        self.assertEqual(self.app.tree.selection(), (second,))
        with patch('linuxdm.__main__.subprocess.Popen') as launch:
            self.app.open_directory()
            self.assertEqual(launch.call_args.args[0], ['xdg-open', self.temp.name])

    def test_category_suggestions_and_custom_destination_override(self):
        self.app.add_dialog()
        fields = self.app.dialog_fields
        fields['url'].set('https://example.invalid/report.PDF?token=abc')
        self.assertEqual(fields['directory'].get(), str(Path(self.app.directory) / 'Documents'))
        fields['url'].set('https://example.invalid/movie.mp4')
        self.assertEqual(fields['directory'].get(), str(Path(self.app.directory) / 'Videos'))
        custom = str(Path(self.temp.name) / 'My files')
        fields['directory'].set(custom)
        fields['url'].set('https://example.invalid/archive.zip')
        self.assertEqual(fields['directory'].get(), custom)
        fields['category'].set('Music')
        fields['category'].event_generate('<<ComboboxSelected>>')
        self.root.update()
        self.assertEqual(fields['directory'].get(), str(Path(self.app.directory) / 'Music'))
        self.app.dialog_start.invoke()
        self.assertEqual(Path(self.manager.snapshot()[0]['target']).parent, Path(self.app.directory) / 'Music')

    def test_incoming_streaming_video_defaults_to_videos_even_when_deferred(self):
        enqueue('https://www.youtube.com/watch?v=example', self.manager.root, kind='video', title='Movie')
        self.refresh_now()
        expected = Path(self.app.directory) / 'Videos'
        self.assertEqual(self.app.dialog_fields['directory'].get(), str(expected))
        # Closing the dialog must retain the category folder too.
        self.app.dialog.event_generate('<Escape>')
        self.root.update()
        self.assertEqual(Path(self.manager.snapshot()[0]['target']).parent, expected)

    def test_autostart_menu_saves_selected_preference(self):
        with patch('linuxdm.__main__.set_autostart') as save:
            self.app.autostart.set(True)
            self.app.toggle_autostart()
            save.assert_called_once_with(True)
            self.assertIn('start hidden', self.app.footer.cget('text'))
            save.reset_mock()
            self.app.autostart.set(False)
            self.app.toggle_autostart()
            save.assert_called_once_with(False)

    def test_control_a_selects_visible_downloads_and_respects_filter(self):
        first = self.manager.add('https://example.invalid/one.zip', self.temp.name)
        second = self.manager.add('https://example.invalid/two.zip', self.temp.name)
        self.refresh_now()
        self.app.tree.focus_force()
        self.root.update()
        self.app.tree.event_generate('<Control-a>')
        self.root.update()
        self.assertEqual(set(self.app.tree.selection()), {first, second})
        self.app.search.set('one')
        self.app.render()
        self.app.tree.event_generate('<Control-a>')
        self.root.update()
        self.assertEqual(self.app.tree.selection(), (first,))
        self.app.search.set('no-matches')
        self.app.render()
        self.assertEqual(self.app.select_all_downloads(), 'break')
        self.assertEqual(self.app.tree.selection(), ())

    def test_controls_remain_visible_at_minimum_size(self):
        self.root.geometry('900x560')
        self.root.update()
        for widget in (self.app.pause_button, self.app.resume_button, self.app.progress, self.app.footer,
                       self.app.remove_button, self.app.clear_button, self.app.move_button, self.app.queue_toggle):
            self.assertTrue(widget.winfo_ismapped())
            self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(),
                                 self.root.winfo_rooty() + self.root.winfo_height())
            self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(),
                                 self.root.winfo_rootx() + self.root.winfo_width())
        self.assertGreater(self.app.tree.winfo_height(), 100)
        self.assertEqual(str(self.app.pause_button['state']), 'disabled')
        self.assertEqual(self.root.cget('bg'), '#17191d')
        self.assertEqual(int(self.app.tree.tk.call('ttk::style', 'lookup', 'Treeview', '-rowheight')), 30)

    def test_create_rename_filter_and_move_named_queue(self):
        self.app.manage_queues()
        self.root.update()
        editor = self.app.queue_editor
        editor['name'].set('Learning')
        editor['count'].set('1')
        editor['create']()
        custom = next(q['id'] for q in self.manager.queue_snapshot() if q['name'] == 'Learning')
        editor['name'].set('Tutorials')
        editor['save']()
        self.app.dialog.destroy()
        default_job = self.manager.add('https://example.invalid/default.zip', self.temp.name)
        custom_job = self.manager.add('https://example.invalid/tutorial.zip', self.temp.name, queue_id=custom)
        self.app.queue_filter = custom
        self.refresh_now()
        self.assertEqual(self.app.tree.get_children(), (custom_job,))
        self.app.toggle_queue()
        self.assertTrue(next(q for q in self.manager.queue_snapshot() if q['id'] == custom)['paused'])
        self.app.tree.selection_set(custom_job)
        self.app.move_selected('default')
        self.assertEqual(self.app.tree.get_children(), ())
        self.app.queue_filter = None
        self.app.render()
        self.assertEqual(set(self.app.tree.get_children()), {default_job, custom_job})

    def test_streaming_video_dialog_selects_queue_and_quality(self):
        custom = self.manager.save_queue('Videos', 1)
        enqueue('https://www.youtube.com/watch?v=example', self.manager.root,
                kind='video', title='Sample video')
        self.refresh_now()
        self.assertEqual(self.app.dialog_fields['kind'].get(), 'Streaming video')
        self.app.dialog_fields['queue'].current(1)
        self.app.dialog_fields['quality'].current(2)
        self.app.dialog_start.invoke()
        self.root.update()
        job = self.manager.snapshot()[0]
        self.assertEqual(job['queue_id'], custom)
        self.assertEqual(job['kind'], 'video')
        self.assertEqual(job['quality'], '720')
        self.assertEqual(job['status'], 'Queued')

    def test_pause_resume_and_filter_order(self):
        first = self.manager.add('https://example.invalid/first.zip', self.temp.name)
        second = self.manager.add('https://example.invalid/second.zip', self.temp.name)
        self.app.jobs = self.manager.snapshot()
        self.app.render()
        self.app.tree.selection_set(first)
        self.root.update()
        self.app.pause_button.invoke()
        self.root.update()
        self.assertEqual(self.manager.snapshot()[0]['status'], 'Paused')
        self.assertEqual(str(self.app.resume_button['state']), 'normal')
        self.app.resume_button.invoke()
        self.assertEqual(self.manager.snapshot()[0]['status'], 'Queued')
        self.app.search.set('second')
        self.assertEqual(self.app.tree.get_children(), (second,))
        self.app.search.set('')
        self.assertEqual(self.app.tree.get_children(), (first, second))
        self.app.action('pause', all_jobs=True)
        self.app.set_filter('Paused')
        self.assertEqual(self.app.tree.get_children(), (first, second))

    def test_new_download_dialog(self):
        self.app.add_dialog()
        self.root.update()
        self.assertTrue(self.app.dialog.winfo_ismapped())
        self.assertEqual(self.app.dialog.grab_current(), self.app.dialog)
        self.app.dialog.destroy()

    def test_downloaded_size_and_chrome_inbox(self):
        request_id = enqueue('https://example.invalid/from-chrome.zip', self.manager.root)
        self.root.after_cancel(self.app.refresh_timer)
        self.app.refresh()
        self.root.update()
        self.assertEqual(self.app.tree.selection(), (request_id,))
        self.assertEqual(self.app.tree.set(request_id, 'downloaded'), '0.0 B')
        self.assertEqual(self.app.tree.set(request_id, 'size'), '—')
        self.manager.jobs[0].update(done=5 * 1024 * 1024, total=10 * 1024 * 1024)
        self.app.jobs = self.manager.snapshot()
        self.app.render()
        self.assertEqual(self.app.tree.set(request_id, 'downloaded'), '5.0 MiB')
        self.assertEqual(self.app.tree.set(request_id, 'size'), '10.0 MiB')

    def test_chrome_dialog_edits_destination_and_starts_download(self):
        request_id = enqueue('https://example.invalid/from-chrome.zip', self.manager.root)
        self.refresh_now()
        self.assertEqual(self.app.dialog.title(), 'Download from browser')
        self.assertEqual(self.manager.snapshot()[0]['status'], 'Ready')
        self.app.dialog_fields['directory'].set(str(Path(self.temp.name) / 'chosen-folder'))
        self.app.dialog_fields['filename'].set('chosen.zip')
        self.app.dialog_fields['connections'].set('2')
        self.app.dialog_start.invoke()
        self.root.update()
        job = self.manager.snapshot()[0]
        self.assertEqual(job['id'], request_id)
        self.assertEqual(job['status'], 'Queued')
        self.assertEqual(job['target'], str(Path(self.temp.name) / 'chosen-folder/chosen.zip'))
        self.assertEqual(job['connections'], 2)
        self.assertFalse(self.app.dialog.winfo_exists())

    def test_multiple_chrome_dialogs_later_and_discard(self):
        first = enqueue('https://example.invalid/first.zip', self.manager.root)
        second = enqueue('https://example.invalid/second.zip', self.manager.root)
        for request_id in (first, second):
            os.utime(self.manager.root / 'inbox' / f'{request_id}.json', ns=(1000000000, 1000000000))
        self.refresh_now()
        self.assertEqual(self.app.dialog_fields['url'].get(), 'https://example.invalid/first.zip')
        self.app.dialog_later.invoke()
        self.refresh_now()
        self.assertEqual(self.manager.snapshot()[0]['status'], 'Paused')
        self.assertEqual(self.app.dialog_fields['url'].get(), 'https://example.invalid/second.zip')
        self.app.dialog_discard.invoke()
        self.refresh_now()
        self.assertEqual([j['id'] for j in self.manager.snapshot()], [first])
        self.assertFalse(self.app.dialog.winfo_exists())
        self.assertFalse(self.app.tree.exists(second))

    def test_incoming_link_does_not_overwrite_manual_dialog(self):
        self.app.add_dialog()
        original = self.app.dialog
        enqueue('https://example.invalid/pending.zip', self.manager.root)
        self.refresh_now()
        self.assertIs(self.app.dialog, original)
        self.assertEqual(self.app.dialog.title(), 'New download')
        original.destroy()
        self.refresh_now()
        self.assertEqual(self.app.dialog.title(), 'Download from browser')
        # Window-close behaves like Download later, rather than losing the link.
        self.app.dialog.tk.call(self.app.dialog.protocol('WM_DELETE_WINDOW'))
        self.refresh_now()
        self.assertEqual(self.manager.snapshot()[0]['status'], 'Paused')
        self.assertFalse(self.app.dialog.winfo_exists())

    def test_remove_selected_and_clear_completed_controls(self):
        first = self.manager.add('https://example.invalid/first.zip', self.temp.name)
        second = self.manager.add('https://example.invalid/second.zip', self.temp.name)
        target = Path(self.manager.snapshot()[1]['target'])
        target.write_bytes(b'finished download')
        self.manager.jobs[1]['status'] = 'Complete'
        self.refresh_now()
        self.app.tree.selection_set(first)
        self.root.update()
        self.app.remove_button.invoke()
        self.root.update()
        self.assertFalse(self.app.tree.exists(first))
        self.app.clear_button.invoke()
        self.root.update()
        self.assertFalse(self.app.tree.exists(second))
        self.assertEqual(self.manager.snapshot(), [])
        self.assertEqual(target.read_bytes(), b'finished download')
