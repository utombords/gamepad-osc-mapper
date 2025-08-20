Gamepad OSC Mapper
===================

[![Build & Release](https://img.shields.io/github/actions/workflow/status/utombords/gamepad-osc-mapper/release.yml?label=build%20%26%20release)](https://github.com/utombords/gamepad-osc-mapper/actions)
[![Lint](https://img.shields.io/github/actions/workflow/status/utombords/gamepad-osc-mapper/lint.yml?label=lint)](https://github.com/utombords/gamepad-osc-mapper/actions)

Gamepad OSC Mapper lets you map inputs from XInput (Xbox) and JoyShockLibrary (DualShock/DualSense/Switch) controllers to OSC messages over UDP. Configure mappings in a local web UI, send to any OSC target on your LAN, and tune rate/format precisely.

Features
- Map buttons, sticks, triggers, and IMU to OSC
- Modes: direct, rate, toggle, step, reset, set from input, layer switch
- 60 Hz “burst while moving” with low idle CPU
- String channels (two-state) and variable expansion in addresses/strings
- Per-channel ranges and defaults; endpoint snapping for stable edges
- Config saved next to the EXE (portable)
- Optional Local Bind IP and OSC bundles toggle (compatibility)

Quick start (Windows one‑file)
1) Download the latest release EXE from GitHub Releases
2) Place it in a folder you control (it creates `configs/` beside the EXE)
3) Run the EXE, open the UI at `http://127.0.0.1:5000`
4) Set OSC target IP/port in Settings → OSC Server
5) Map inputs in Layer A and test

Network tips
- If your target uses broadcast, set IP to your subnet broadcast (e.g., `192.168.1.255`).
- Some receivers do not support OSC bundles: uncheck “Use OSC Bundles” (Settings → OSC Server).
- If you have multiple NICs, set “Local Bind IP” to your LAN IP so packets leave the correct adapter.
- Windows Firewall can block outbound UDP for unknown EXEs; allow outbound for the EXE on Private networks.

Controllers
- XInput: up to 4 slots (X0–X3). Sticks −1..1, triggers 0..1. Deadzones/curve in Settings.
- JoyShockLibrary (DualShock/DualSense/Switch): buttons, sticks, triggers, optional IMU.

Build from source
Prereqs: Python 3.10+, pip

Install
```
pip install -r requirements.txt
```

Run (dev)
```
python -m app.main
```

Build one‑file (PyInstaller)
```
pip install pyinstaller
pyinstaller --clean --noconfirm main.spec
```
The EXE will be in `dist/`.

Repository structure
- `app/` backend services (OSC, input, config, web)
- `static/` frontend JS/CSS
- `templates/` HTML
- `configs/` active and presets (created at runtime)

Releases and versioning
- Semantic versioning (MAJOR.MINOR.PATCH)
- Release notes list features, fixes, and known issues

Third‑party notices
- See `THIRD_PARTY_NOTICES.md` for bundled libraries and licenses. For JoyShockLibrary changes, see `docs/JoyShockLibraryMOD.txt`.

License
This project is licensed under the MIT License. See `LICENSE`.

Security/Reporting
Please open an issue for non-sensitive bugs. For sensitive reports, contact the maintainer privately.

Acknowledgements
- python-osc, Flask, Flask‑SocketIO, JoyShockLibrary, XInput (Python package)


