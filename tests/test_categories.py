import unittest
from linuxdm.categories import detect_category, suggested_directory


class CategoryTest(unittest.TestCase):
    def test_common_extensions_and_unknown_files(self):
        for name, category in [('movie.MKV', 'Videos'), ('song.flac', 'Music'), ('report.pdf', 'Documents'),
                               ('photo.jpeg', 'Pictures'), ('source.tar.gz', 'Archives'),
                               ('app.AppImage', 'Programs'), ('unknown', 'Other')]:
            self.assertEqual(detect_category('https://example.com/' + name + '?token=1'), category)

    def test_chrome_filename_takes_precedence_and_streams_always_use_videos(self):
        self.assertEqual(detect_category('https://example.com/download', 'Report.PDF'), 'Documents')
        self.assertEqual(detect_category('https://example.com/a.zip', 'movie', 'video'), 'Videos')
        self.assertEqual(suggested_directory('/tmp/Downloads', 'https://example.com/a%2Epdf'), '/tmp/Downloads/Documents')
