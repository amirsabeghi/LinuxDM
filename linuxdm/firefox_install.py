"""Register Firefox's native messaging host for the current user."""
import json
import os
import sys
from pathlib import Path
from .bridge import HOST_NAME, state_dir

EXTENSION_ID = 'linuxdm@linuxdm.local'


def install(home=None, data_root=None, project=None):
    home = Path(home or Path.home())
    data_root = Path(data_root or state_dir())
    project = Path(project or Path(__file__).resolve().parent.parent).resolve()
    data_root.mkdir(parents=True, exist_ok=True)
    launcher = data_root / 'firefox-native-host'
    launcher.write_text(f'#!{sys.executable}\nimport sys\nsys.path.insert(0, {str(project)!r})\n'
                        'from linuxdm.native_host import main\nmain()\n')
    launcher.chmod(0o700)
    folder = home / '.mozilla/native-messaging-hosts'
    folder.mkdir(parents=True, exist_ok=True)
    manifest = folder / f'{HOST_NAME}.json'
    manifest.write_text(json.dumps(dict(name=HOST_NAME, description='LinuxDM desktop bridge',
        path=str(launcher.resolve()), type='stdio', allowed_extensions=[EXTENSION_ID]), indent=2)+'\n')
    return manifest


def main():
    if os.name == 'nt':
        from .windows_install import register_browsers
        register_browsers(Path(__file__).resolve().parent.parent)
    else:
        print(f'Registered: {install()}')


if __name__ == '__main__':
    main()
