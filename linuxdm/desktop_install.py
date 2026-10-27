"""Install LinuxDM in the current user's Linux application menu."""
import configparser
import os
import shutil
import sys
from pathlib import Path


def desktop_quote(value):
    # Exec is parsed by the desktop launcher, not by a shell.
    value = str(value).replace('%', '%%')
    for char in ('\\', '"', '`', '$'):
        value = value.replace(char, '\\' + char)
    return '"' + value.replace('\\', '\\\\') + '"'


def install(data_home=None, project=None):
    data = Path(data_home or os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')).resolve()
    project = Path(project or Path(__file__).resolve().parent.parent).resolve()
    folder = data / 'linuxdm'
    folder.mkdir(parents=True, exist_ok=True)
    launcher = folder / 'linuxdm'
    launcher.write_text(f'#!{sys.executable}\nimport sys\nsys.path.insert(0, {str(project)!r})\n'
                        'from linuxdm.__main__ import main\nmain()\n')
    launcher.chmod(0o755)
    icons = data / 'icons/hicolor/128x128/apps'
    icons.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(project / 'chrome-extension/icon128.png', icons / 'io.linuxdm.png')
    applications = data / 'applications'
    applications.mkdir(parents=True, exist_ok=True)
    desktop = applications / 'io.linuxdm.desktop'
    desktop.write_text('[Desktop Entry]\nType=Application\nName=LinuxDM\n'
                       'Comment=Manage file and video downloads\n'
                       f'Exec={desktop_quote(launcher)}\nIcon=io.linuxdm\n'
                       'Terminal=false\nCategories=Network;FileTransfer;\n'
                       'StartupWMClass=Linuxdm\nKeywords=download;video;queue;\n'
                       'Actions=Background;\n\n[Desktop Action Background]\n'
                       'Name=Start in background\n'
                       f'Exec={desktop_quote(launcher)} --background\n')
    # Remove the extra launcher installed by earlier versions.
    (applications / 'io.linuxdm.background.desktop').unlink(missing_ok=True)
    return desktop


def autostart_path(config_home=None):
    return Path(config_home or os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'autostart/io.linuxdm.desktop'


def autostart_enabled(config_home=None):
    config = configparser.ConfigParser(interpolation=None)
    try:
        config.read(autostart_path(config_home))
        return config.has_section('Desktop Entry') and not config.getboolean('Desktop Entry', 'Hidden', fallback=False)
    except (OSError, ValueError, configparser.Error):
        return False


def set_autostart(enabled, config_home=None, data_home=None):
    target = autostart_path(config_home)
    if enabled:
        desktop = install(data_home=data_home)
        launcher = desktop.parent.parent / 'linuxdm/linuxdm'
        source = ('[Desktop Entry]\nType=Application\nName=LinuxDM\n'
                  'Comment=Run LinuxDM in the background at login\n'
                  f'Exec={desktop_quote(launcher)} --background\n'
                  'Icon=io.linuxdm\nTerminal=false\nHidden=false\n')
    else:
        source = '[Desktop Entry]\nType=Application\nName=LinuxDM\nHidden=true\n'
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.tmp')
    temporary.write_text(source)
    temporary.replace(target)
    return target


def main():
    print(f'Installed: {install()}')
    print('Open LinuxDM from your application menu. Closing the window keeps downloads running.')


if __name__ == '__main__':
    main()
