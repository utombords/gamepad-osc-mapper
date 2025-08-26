# -*- mode: python ; coding: utf-8 -*-

import sys
from PyInstaller.utils.hooks import collect_submodules, collect_dynamic_libs, collect_data_files

block_cipher = None

# Filter Qt plugins util
def _filter_qt_plugins(items):
    def _keep(entry):
        src = entry[0] if isinstance(entry, tuple) else entry
        p = str(src).replace('\\', '/').lower()
        if '/plugins/' in p:
            # Keep only the minimal window platform plugin; drop everything else
            return '/plugins/platforms/' in p
        return True
    return [e for e in items if _keep(e)]

# Shared hidden imports (no Qt) – keep minimal for threading mode
cli_hidden = [
    'engineio.async_drivers.threading',
]

# GUI hidden imports add Qt
gui_hidden = list(cli_hidden)
gui_hidden += [
    'PySide6',
    'shiboken6',
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
]

try:
    pyside6_datas = collect_data_files('PySide6')
    pyside6_binaries = collect_dynamic_libs('PySide6')
except Exception:
    pyside6_datas, pyside6_binaries = [], []

pyside6_datas = _filter_qt_plugins(pyside6_datas)
pyside6_binaries = _filter_qt_plugins(pyside6_binaries)

# Shared app data
shared_datas = [
    ('templates', 'templates'),
    ('static', 'static'),
    ('app/definitions', 'app/definitions'),
    ('app/lib', 'app/lib'),
]

# --- GUI build (separate analysis including Qt) ---
a_gui = Analysis(
    ['app/gui_main_qt.py'],
    pathex=[],
    binaries=pyside6_binaries,
    datas=shared_datas + pyside6_datas,
    hiddenimports=gui_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6.QtNetwork', 'PySide6.QtPrintSupport', 'PySide6.QtSvg', 'PySide6.QtQml', 'PySide6.QtQuick',
              'PySide6.QtWebSockets', 'PySide6.QtWebEngineCore', 'PySide6.QtMultimedia', 'PySide6.QtNetworkAuth',
              'PySide6.QtBluetooth', 'PySide6.QtSerialPort', 'PySide6.QtPositioning', 'PySide6.QtSensors', 'PySide6.QtSql',
              'tkinter', '_tkinter', 'PyQt5', 'PyQt6'],
    noarchive=False,
)
pyz_gui = PYZ(a_gui.pure, a_gui.zipped_data, cipher=block_cipher)
gui_exe = EXE(
    pyz_gui,
    a_gui.scripts,
    a_gui.binaries,
    a_gui.zipfiles,
    a_gui.datas,
    name='GamepadOSCMapper-GUI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    onefile=True,
)

# --- CLI build (no Qt) ---
a_cli = Analysis(
    ['app/main.py'],
    pathex=[],
    binaries=[],
    datas=shared_datas,
    hiddenimports=cli_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6', 'shiboken6', 'PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets', 'tkinter', '_tkinter',
              'eventlet', 'gevent', 'geventwebsocket', 'aiohttp', 'sanic', 'tornado', 'redis', 'kombu', 'kafka',
              'aioredis', 'msgpack', 'uvloop', 'OpenSSL', 'watchdog', 'setuptools', 'pkg_resources', 'win32com'],
    noarchive=False,
)
pyz_cli = PYZ(a_cli.pure, a_cli.zipped_data, cipher=block_cipher)

# CLI onefile
cli_onefile = EXE(
    pyz_cli,
    a_cli.scripts,
    a_cli.binaries,
    a_cli.zipfiles,
    a_cli.datas,
    name='GamepadOSCMapper-CLI-OneFile',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    onefile=True,
)


