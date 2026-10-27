"""Windows per-user browser registration and startup integration."""
import json
import subprocess
import sys
from pathlib import Path
from .chrome_install import extension_id
from .firefox_install import EXTENSION_ID
from .bridge import HOST_NAME

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'


def autostart_enabled():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, 'LinuxDM')
        return True
    except FileNotFoundError:
        return False


def set_autostart(enabled):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enabled:
            python = str(Path(sys.executable).with_name('pythonw.exe'))
            launch = str(Path(__file__).resolve().parent.parent / 'launch.pyw')
            winreg.SetValueEx(key, 'LinuxDM', 0, winreg.REG_SZ,
                             subprocess.list2cmdline([python, launch, '--background']))
        else:
            try:
                winreg.DeleteValue(key, 'LinuxDM')
            except FileNotFoundError:
                pass


def register_browsers(project):
    import winreg
    project = Path(project).resolve()
    python = str(Path(sys.executable).with_name('python.exe'))
    # Browsers launch this batch file with a native stdio channel.
    launcher = project / 'native-host.cmd'
    launcher.write_text('@echo off\r\n' + subprocess.list2cmdline([python, str(project / 'native_host_entry.py')]) + '\r\n')
    for browser, registry, allowed in (
        ('chrome', r'Software\Google\Chrome\NativeMessagingHosts', {'allowed_origins': [f'chrome-extension://{extension_id(project)}/']}),
        ('firefox', r'Software\Mozilla\NativeMessagingHosts', {'allowed_extensions': [EXTENSION_ID]})):
        manifest = project / f'{browser}-native-host.json'
        manifest.write_text(json.dumps(dict(name=HOST_NAME, description='LinuxDM desktop bridge',
            path=str(launcher), type='stdio', **allowed), indent=2))
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, registry + '\\' + HOST_NAME) as key:
            winreg.SetValueEx(key, '', 0, winreg.REG_SZ, str(manifest))


if __name__ == '__main__':
    register_browsers(Path(__file__).resolve().parent.parent)
