# gamepad_osc_mapper.spec

import os
import sys

# Function to get the base path (useful for PyInstaller hooks or bundled files)
def get_base_path():
    if getattr(sys, 'frozen', False):
        # The application is frozen
        return os.path.dirname(sys.executable)
    else:
        # The application is not frozen
        return os.path.dirname(__file__)

# Application Name
app_name = 'GamepadOSCMapper'

# Determine current working directory, which should be the project root
project_root = os.getcwd()

# Paths to your main script and icon
main_script = os.path.join(project_root, 'app', 'main.py')
icon_file = os.path.join(project_root, 'static', 'favicon.ico')
version_file = os.path.join(project_root, 'version_info.txt')

# Collect data files
# Syntax: (source_path_on_disk, destination_in_bundle)
datas = [
    # Definitions
    (os.path.join(project_root, 'app', 'definitions'), 'app/definitions'),
    # Static files for web UI
    (os.path.join(project_root, 'static'), 'static'),
    # Template files for web UI
    (os.path.join(project_root, 'templates'), 'templates'),
    # If you have a default config.json you want to bundle, add it here
    # e.g., (os.path.join(project_root, 'default_config.json'), '.')
]

# Collect binary files (DLLs, etc.)
# Collect binary files (DLLs, etc.). Include only if present to keep CI builds green.
binaries = []
_dll_candidates = [
    os.path.join(project_root, 'app', 'lib', 'JoyShockLibrary.dll'),
    os.path.join(project_root, 'app', 'lib', 'hidapi.dll'),
]
for _dll in _dll_candidates:
    if os.path.exists(_dll):
        binaries.append((_dll, '.'))

# Hidden imports that PyInstaller might miss
# Include Engine.IO threading driver for Flask-SocketIO in frozen builds
hiddenimports = [
    'engineio.async_drivers.threading'
]

# Runtime hooks (scripts run before your main script) — none needed for threading mode
runtime_hooks = []

a = Analysis(
    [main_script],
    pathex=[project_root], # Add project root to Python path for PyInstaller
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[], # You can specify a directory for custom PyInstaller hooks
    runtime_hooks=runtime_hooks,
    excludes=['tkinter', '_tkinter', 'eventlet', 'gevent', 'geventwebsocket'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=app_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # Disable UPX to reduce false-positive detections by AV
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # True for a console window (debug), False for a GUI app (no console)
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_file,
    version=version_file,
)

# Also build a one-directory bundle (more AV-friendly, includes DLLs alongside exe)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=app_name,
)
