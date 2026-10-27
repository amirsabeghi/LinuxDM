"""Build a relocatable Debian package without changing the host system."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from linuxdm.chrome_install import extension_id
from linuxdm.firefox_install import EXTENSION_ID


def build():
    stage = ROOT / '.build/debian'
    if stage.exists():
        shutil.rmtree(stage)
    app = stage / 'usr/share/linuxdm'
    for name in ('linuxdm', 'chrome-extension', 'firefox-extension'):
        shutil.copytree(ROOT / name, app / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copyfile(ROOT / 'README.md', app / 'README.md')
    for name, module in [('linuxdm', 'linuxdm.__main__'), ('linuxdm-native-host', 'linuxdm.native_host')]:
        path = stage / 'usr/bin' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('#!/usr/bin/python3\nimport sys\nsys.path.insert(0, "/usr/share/linuxdm")\n'
                        f'from {module} import main\nmain()\n')
        path.chmod(0o755)
    base = dict(name='io.linuxdm.bridge', description='LinuxDM browser bridge', path='/usr/bin/linuxdm-native-host', type='stdio')
    for folder, allowed in [('etc/opt/chrome/native-messaging-hosts', {'allowed_origins': [f'chrome-extension://{extension_id(ROOT)}/']}),
                            ('etc/chromium/native-messaging-hosts', {'allowed_origins': [f'chrome-extension://{extension_id(ROOT)}/']}),
                            ('usr/lib/mozilla/native-messaging-hosts', {'allowed_extensions': [EXTENSION_ID]})]:
        path = stage / folder / 'io.linuxdm.bridge.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dict(base, **allowed), indent=2)+'\n')
    desktop = stage / 'usr/share/applications/io.linuxdm.desktop'
    desktop.parent.mkdir(parents=True)
    desktop.write_text('[Desktop Entry]\nType=Application\nName=LinuxDM\nExec=linuxdm\nIcon=io.linuxdm\n'
                       'Terminal=false\nCategories=Network;FileTransfer;\nStartupWMClass=Linuxdm\nActions=Background;\n'
                       '\n[Desktop Action Background]\nName=Start in background\nExec=linuxdm --background\n')
    icon = stage / 'usr/share/icons/hicolor/128x128/apps/io.linuxdm.png'
    icon.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / 'chrome-extension/icon128.png', icon)
    control = stage / 'DEBIAN/control'
    control.parent.mkdir()
    control.write_text('Package: linuxdm\nVersion: 0.5.0\nArchitecture: all\nMaintainer: LinuxDM project <linuxdm@localhost>\n'
        'Section: net\nPriority: optional\nDepends: python3 (>= 3.10), python3-tk, python3-gi, gir1.2-gtk-3.0, gir1.2-ayatanaappindicator3-0.1\n'
        'Recommends: ffmpeg, yt-dlp\nDescription: Desktop download manager with browser integration\n'
        ' Persistent named queues, parallel connections, video downloads, and tray controls.\n')
    out = ROOT / 'dist/linuxdm_0.5.0_all.deb'
    subprocess.run(['dpkg-deb', '--root-owner-group', '--build', str(stage), str(out)], check=True)


if __name__ == '__main__':
    build()
