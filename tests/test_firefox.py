import json
import tempfile
import unittest
from pathlib import Path
from linuxdm.firefox_install import install, EXTENSION_ID


class FirefoxTest(unittest.TestCase):
    def test_host_registration_uses_firefox_identity_and_location(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            manifest = install(home=home, data_root=home / 'data')
            self.assertEqual(manifest.parent, home / '.mozilla/native-messaging-hosts')
            data = json.loads(manifest.read_text())
            self.assertEqual(data['allowed_extensions'], [EXTENSION_ID])
            self.assertNotIn('allowed_origins', data)
            self.assertTrue(Path(data['path']).stat().st_mode & 0o100)

    def test_firefox_manifest_has_event_page_and_no_chrome_key(self):
        manifest = json.loads((Path(__file__).resolve().parent.parent / 'firefox-extension/manifest.json').read_text())
        self.assertEqual(manifest['background'], {'scripts': ['background.js']})
        self.assertNotIn('key', manifest)
        self.assertEqual(manifest['browser_specific_settings']['gecko']['id'], EXTENSION_ID)
