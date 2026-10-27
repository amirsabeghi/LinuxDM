"""Build the Firefox variant from the shared Chrome extension sources."""
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def build():
    source = ROOT / 'chrome-extension'
    target = ROOT / 'firefox-extension'
    target.mkdir(exist_ok=True)
    for file in source.iterdir():
        if file.is_file():
            shutil.copyfile(file, target / file.name)
    manifest = json.loads((target / 'manifest.json').read_text())
    manifest.pop('key', None)
    manifest['version'] = '0.5.0'
    manifest['background'] = {'scripts': ['background.js']}
    manifest['browser_specific_settings'] = {'gecko': {'id': 'linuxdm@linuxdm.local',
        'strict_min_version': '140.0', 'data_collection_permissions': {'required': ['none']}}}
    (target / 'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    for file in ('popup.html', 'popup.js'):
        p = target / file
        p.write_text(p.read_text().replace('Chrome', 'Firefox').replace('linuxdm.chrome_install', 'linuxdm.firefox_install'))
    out = ROOT / 'dist/linuxdm-firefox-0.5.0-unsigned.xpi'
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(target.iterdir()):
            archive.write(file, file.name)
    print(out)


if __name__ == '__main__':
    build()
