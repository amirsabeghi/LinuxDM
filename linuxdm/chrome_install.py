"""Register the local native messaging bridge for Chrome and Chromium."""
import argparse
import base64
import hashlib
import json
import os
import sys
from pathlib import Path
from .bridge import HOST_NAME, state_dir


def extension_id(project):
    manifest = json.loads((Path(project) / 'chrome-extension/manifest.json').read_text())
    public_key = base64.b64decode(manifest['key'], validate=True)
    digest = hashlib.sha256(public_key).hexdigest()[:32]
    return ''.join(chr(ord('a') + int(char, 16)) for char in digest)


def install(config_root, data_root, project):
    project = Path(project).resolve()
    data_root = Path(data_root).resolve()
    data_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    launcher = data_root / 'chrome-native-host'
    source = (f'#!{sys.executable}\n'
              'import sys\n'
              f'sys.path.insert(0, {str(project)!r})\n'
              'from linuxdm.native_host import main\n'
              'main()\n')
    launcher.write_text(source)
    launcher.chmod(0o700)
    manifest = dict(name=HOST_NAME, description='LinuxDM desktop download bridge',
                    path=str(launcher), type='stdio',
                    allowed_origins=[f'chrome-extension://{extension_id(project)}/'])
    paths = []
    for browser in ('google-chrome', 'chromium'):
        folder = Path(config_root) / browser / 'NativeMessagingHosts'
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f'{HOST_NAME}.json'
        target.write_text(json.dumps(manifest, indent=2) + '\n')
        paths.append(target)
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config-root', type=Path,
                        default=Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')))
    parser.add_argument('--data-root', type=Path, default=state_dir(),
                        help='Where to install the executable bridge (not the download queue).')
    args = parser.parse_args()
    project = Path(__file__).resolve().parent.parent
    for path in install(args.config_root, args.data_root, project):
        print(f'Registered: {path}')
    print(f'Extension ID: {extension_id(project)}')
    print(f'In chrome://extensions enable Developer mode, choose Load unpacked, and select:\n{project / "chrome-extension"}')


if __name__ == '__main__':
    main()
