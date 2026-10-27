"""Stage Windows files and compile the NSIS installer using downloaded build inputs."""
import hashlib
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def build():
    runtime = ROOT / '.build/python-runtime-verified.exe'
    expected = 'fb4f9f5d438b2396da0086dc70b935c530cb578e37adc6d354f7ad2037fee83b'
    if hashlib.sha256(runtime.read_bytes()).hexdigest() != expected:
        raise ValueError('Python runtime checksum does not match python.org')
    stage = ROOT / '.build/windows-payload'
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir()
    for name in ('linuxdm', 'chrome-extension', 'firefox-extension'):
        shutil.copytree(ROOT / name, stage / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in ('launch.pyw', 'native_host_entry.py'):
        shutil.copyfile(ROOT / 'packaging' / name, stage / name)
    shutil.copyfile(ROOT / 'README.md', stage / 'README.md')
    vendor = stage / 'vendor'
    vendor.mkdir()
    wheels = list((ROOT / '.build/wheels').glob('*.whl'))
    for prefix in ('pystray-', 'pillow-', 'six-'):
        if not any(p.name.lower().startswith(prefix) for p in wheels):
            raise ValueError(f'Missing offline wheel: {prefix}')
    for wheel in wheels:
        with zipfile.ZipFile(wheel) as archive:
            archive.extractall(vendor)
    env = dict(os.environ, NSISDIR=str(ROOT / '.build/nsis/usr/share/nsis'))
    subprocess.run([str(ROOT / '.build/nsis/usr/bin/makensis'), '-V2', 'windows.nsi'],
                   cwd=ROOT / 'packaging', env=env, check=True)


if __name__ == '__main__':
    build()
