import sys
import os
import subprocess
import threading
import time
from typing import Optional

from PySide6 import QtCore, QtWidgets, QtGui
import socketio


class ServerProcessManager(QtCore.QObject):
    server_started = QtCore.Signal()
    server_stopped = QtCore.Signal()
    server_output = QtCore.Signal(str)

    def __init__(self, parent: Optional[QtCore.QObject] = None):
        super().__init__(parent)
        self._proc: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._stop_reader = threading.Event()

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self, env: Optional[dict] = None):
        if self.is_running():
            return
        python_exe = sys.executable
        # Determine proper working directory for server launch
        if getattr(sys, 'frozen', False):
            # For onefile/onefolder, use the directory containing the EXE
            cwd = os.path.dirname(sys.executable)
            cmd = [python_exe, "--server"]
        else:
            # From source, ensure CWD is project root so `-m app.main` works
            cwd = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
            cmd = [python_exe, "-m", "app.main"]
        self._proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=self._compose_env(env),
        )
        self._stop_reader.clear()
        self._reader_thread = threading.Thread(target=self._read_stdout_loop, daemon=True)
        self._reader_thread.start()
        self.server_started.emit()

    def _compose_env(self, extra: Optional[dict]) -> dict:
        new_env = (extra or os.environ).copy()
        # Signal the child process to run the server only (no GUI)
        new_env['GAMEPAD_OSC_RUN_MODE'] = 'server'
        # Enable verbose Socket.IO/Engine.IO logging on the server subprocess for diagnostics
        new_env['SOCKETIO_LOGGERS'] = '1'
        return new_env

    def stop(self):
        if not self.is_running():
            return
        try:
            self._stop_reader.set()
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        finally:
            self._proc = None
            self.server_stopped.emit()

    def _read_stdout_loop(self):
        if not self._proc or not self._proc.stdout:
            return
        for line in self._proc.stdout:
            if self._stop_reader.is_set():
                break
            self.server_output.emit(line.rstrip("\n"))


class SioClient(QtCore.QObject):
    connected = QtCore.Signal()
    disconnected = QtCore.Signal()
    log_line = QtCore.Signal(str)
    config_loaded = QtCore.Signal(dict)
    controller_status_summary = QtCore.Signal(str)

    def __init__(self, parent: Optional[QtCore.QObject] = None):
        super().__init__(parent)
        self._sio = None
        self._host = "127.0.0.1"
        self._port = 5000
        self._create_client()

    def _register_events(self):
        @_wrap(self)
        def on_connect(*_):
            self.connected.emit()
            self.emit_log("[SIO] Connected")
            try:
                self._sio.emit('get_active_config')
                self._sio.emit('get_controller_status')
            except Exception:
                pass

        @_wrap(self)
        def on_disconnect(*_):
            self.emit_log("[SIO] Disconnected")
            self.disconnected.emit()

        @_wrap(self)
        def on_connect_error(data):
            # Data often includes server-provided reason
            self.emit_log(f"[SIO] connect_error: {data}")

        @_wrap(self)
        def on_active_config_updated(data):
            self.config_loaded.emit(data)

        @_wrap(self)
        def on_controller_status_update(data):
            try:
                xinput = data.get('xinput_slots', [])
                jsl = data.get('jsl_devices', [])
                x_count = sum(1 for s in xinput if s and s.get('occupied'))
                j_count = len(jsl)
                self.controller_status_summary.emit(f"XInput: {x_count}  |  JSL: {j_count}")
            except Exception:
                self.controller_status_summary.emit("-")

        self._sio.on('connect', on_connect)
        self._sio.on('disconnect', on_disconnect)
        self._sio.on('connect_error', on_connect_error)
        self._sio.on('active_config_updated', on_active_config_updated)
        self._sio.on('controller_status_update', on_controller_status_update)

    def _create_client(self):
        try:
            if getattr(self, '_sio', None) and getattr(self._sio, 'connected', False):
                self._sio.disconnect()
        except Exception:
            pass
        self._sio = socketio.Client(
            reconnection=True,
            reconnection_attempts=5,
            reconnection_delay=3,
        )
        self._register_events()

    def emit_log(self, text: str):
        self.log_line.emit(text)

    def connect(self, host: str, port: int):
        self._host, self._port = host, port
        url = f"http://{host}:{port}"
        if getattr(self._sio, 'connected', False):
            self.emit_log("[SIO] Already connected")
            return
        threading.Thread(target=self._connect_bg, args=(url,), daemon=True).start()

    def _connect_bg(self, url: str):
        # Single client with auto-reconnect; connect returns immediately and retries in background
        try:
            self.emit_log("[SIO] Connecting...")
            self._sio.connect(url, transports=["polling"], socketio_path="/socket.io")
        except Exception as e:
            # Initial attempt may raise; auto-reconnect will continue in background
            self.emit_log(f"[SIO] Initial connect attempt error: {e}")

    def disconnect(self):
        try:
            self._sio.disconnect()
        except Exception:
            pass

    def is_connected(self) -> bool:
        try:
            return bool(getattr(self._sio, 'connected', False))
        except Exception:
            return False

    def update_osc_settings(self, payload: dict):
        try:
            self._sio.emit('update_osc_settings', payload)
            self.emit_log(f"[SIO] update_osc_settings: {payload}")
        except Exception as e:
            self.emit_log(f"[SIO] update_osc_settings failed: {e}")

    def update_web_settings(self, payload: dict):
        try:
            self._sio.emit('update_web_settings', payload)
            self.emit_log(f"[SIO] update_web_settings: {payload}")
        except Exception as e:
            self.emit_log(f"[SIO] update_web_settings failed: {e}")


def _wrap(owner):
    # Decorator to wrap socketio callbacks so exceptions don’t kill the SIO thread
    def deco(fn):
        def inner(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                try:
                    owner.log_line.emit(f"[SIO] callback error in {fn.__name__}: {e}")
                except Exception:
                    pass
        return inner
    return deco


class ControlPanel(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Gamepad OSC Mapper – Control Panel")
        self.resize(900, 600)

        self._server = ServerProcessManager()
        self._sio = SioClient()

        self._build_ui()
        self._wire_signals()

    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)

        # Top controls
        top_bar = QtWidgets.QHBoxLayout()
        self.btn_start = QtWidgets.QPushButton("Start Server")
        self.btn_stop = QtWidgets.QPushButton("Stop Server")
        self.btn_stop.setEnabled(False)
        self.lbl_server = QtWidgets.QLabel("Server: stopped")
        self.btn_open_browser = QtWidgets.QPushButton("Open Web UI")
        self.lbl_conn = QtWidgets.QLabel("Socket: disconnected")
        top_bar.addWidget(self.btn_start)
        top_bar.addWidget(self.btn_stop)
        top_bar.addStretch(1)
        # Right side order: Open Web UI / Server: ... / Socket: ...
        top_bar.addWidget(self.btn_open_browser)
        top_bar.addSpacing(12)
        top_bar.addWidget(self.lbl_server)
        top_bar.addSpacing(12)
        top_bar.addWidget(self.lbl_conn)
        layout.addLayout(top_bar)

        # Status line for controllers
        self.lbl_devices = QtWidgets.QLabel("Devices: -")
        layout.addWidget(self.lbl_devices)

        splitter = QtWidgets.QSplitter()
        splitter.setOrientation(QtCore.Qt.Orientation.Horizontal)
        layout.addWidget(splitter, 1)

        # Left: settings form
        left_widget = QtWidgets.QWidget()
        left_layout = QtWidgets.QFormLayout(left_widget)
        # OSC settings
        self.osc_ip = QtWidgets.QLineEdit()
        self.osc_port = QtWidgets.QLineEdit()
        self.osc_updates = QtWidgets.QLineEdit()
        self.osc_local_bind_ip = QtWidgets.QLineEdit()
        self.osc_use_bundles = QtWidgets.QCheckBox("Use OSC Bundles")
        left_layout.addRow(QtWidgets.QLabel("OSC IP"), self.osc_ip)
        left_layout.addRow(QtWidgets.QLabel("OSC Port"), self.osc_port)
        left_layout.addRow(QtWidgets.QLabel("Max Updates/sec"), self.osc_updates)
        left_layout.addRow(QtWidgets.QLabel("Local Bind IP (optional)"), self.osc_local_bind_ip)
        left_layout.addRow(self.osc_use_bundles)
        self.btn_save_osc = QtWidgets.QPushButton("Save OSC Settings")
        left_layout.addRow(self.btn_save_osc)
        left_layout.addRow(QtWidgets.QLabel(""))
        # Web settings
        self.web_host = QtWidgets.QLineEdit()
        self.web_port = QtWidgets.QLineEdit()
        self.btn_save_web = QtWidgets.QPushButton("Save Web Settings (restart required)")
        left_layout.addRow(QtWidgets.QLabel("Web Host"), self.web_host)
        left_layout.addRow(QtWidgets.QLabel("Web Port"), self.web_port)
        left_layout.addRow(self.btn_save_web)

        # Right: log output
        right_widget = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_widget)
        self.txt_log = QtWidgets.QTextEdit()
        self.txt_log.setReadOnly(True)
        right_layout.addWidget(self.txt_log)

        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

    def _wire_signals(self):
        self.btn_start.clicked.connect(self._on_start_server)
        self.btn_stop.clicked.connect(self._on_stop_server)
        # Auto-connect only; no manual connect button
        self.btn_save_osc.clicked.connect(self._save_osc_settings)
        self.btn_save_web.clicked.connect(self._save_web_settings)
        self.btn_open_browser.clicked.connect(self._open_web_ui)

        self._server.server_started.connect(lambda: self._set_server_state(True))
        self._server.server_stopped.connect(lambda: self._set_server_state(False))
        self._server.server_output.connect(self._append_log)

        self._sio.connected.connect(lambda: self._set_socket_state(True))
        self._sio.disconnected.connect(lambda: self._set_socket_state(False))
        self._sio.log_line.connect(self._append_log)
        self._sio.config_loaded.connect(self._load_config_into_form)
        self._sio.controller_status_summary.connect(self._set_devices_summary)

    def _append_log(self, line: str):
        self.txt_log.append(line)

    def _set_devices_summary(self, summary: str):
        self.lbl_devices.setText(f"Devices: {summary}")

    def _set_server_state(self, running: bool):
        self.btn_start.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        self.lbl_server.setText("Server: running" if running else "Server: stopped")

    def _set_socket_state(self, connected: bool):
        self.lbl_conn.setText("Socket: connected" if connected else "Socket: disconnected")

    def _on_start_server(self):
        self._server.start()
        # small delay so the server binds before we try to connect
        QtCore.QTimer.singleShot(700, self._auto_connect_if_default)

    def _on_stop_server(self):
        self._server.stop()
        try:
            self._sio.disconnect()
        except Exception:
            pass

    def _auto_connect_if_default(self):
        # Use web settings fields for host/port
        host = (self.web_host.text().strip() if hasattr(self, 'web_host') else '') or "127.0.0.1"
        try:
            port = int((self.web_port.text().strip() if hasattr(self, 'web_port') else '') or "5000")
        except Exception:
            port = 5000
        self._sio.connect(host, port)

    def _load_config_into_form(self, config: dict):
        try:
            osc = config.get('osc_settings', {})
            web = config.get('web_settings', {})
            self.osc_ip.setText(str(osc.get('ip', '127.0.0.1')))
            self.osc_port.setText(str(osc.get('port', 9000)))
            self.osc_updates.setText(str(osc.get('max_updates_per_second', 60)))
            self.osc_local_bind_ip.setText(str(osc.get('local_bind_ip', '') or ''))
            self.osc_use_bundles.setChecked(bool(osc.get('use_bundles', False)))

            self.web_host.setText(str(web.get('host', '127.0.0.1')))
            self.web_port.setText(str(web.get('port', 5000)))
            if not self._sio.is_connected():
                QtCore.QTimer.singleShot(300, self._auto_connect_if_default)
        except Exception as e:
            self._append_log(f"[GUI] Failed to apply config to form: {e}")

    def _save_osc_settings(self):
        try:
            payload = {
                'ip': self.osc_ip.text().strip() or '127.0.0.1',
                'port': int(self.osc_port.text().strip() or '9000'),
                'max_updates_per_second': int(self.osc_updates.text().strip() or '60'),
                'local_bind_ip': self.osc_local_bind_ip.text().strip(),
                'use_bundles': self.osc_use_bundles.isChecked(),
            }
            self._sio.update_osc_settings(payload)
        except Exception as e:
            self._append_log(f"[GUI] Save OSC failed: {e}")

    def _save_web_settings(self):
        try:
            payload = {
                'host': self.web_host.text().strip() or '127.0.0.1',
                'port': int(self.web_port.text().strip() or '5000'),
            }
            self._sio.update_web_settings(payload)
        except Exception as e:
            self._append_log(f"[GUI] Save Web failed: {e}")

    def _open_web_ui(self):
        try:
            host = (self.web_host.text().strip() if hasattr(self, 'web_host') else '') or '127.0.0.1'
            port_text = (self.web_port.text().strip() if hasattr(self, 'web_port') else '') or '5000'
            port = int(port_text)
        except Exception:
            host, port = '127.0.0.1', 5000
        url = QtCore.QUrl(f"http://{host}:{port}")
        QtGui.QDesktopServices.openUrl(url)

    def closeEvent(self, event: QtGui.QCloseEvent):  # type: ignore[name-defined]
        try:
            self._sio.disconnect()
        except Exception:
            pass
        try:
            if self._server.is_running():
                self._server.stop()
        except Exception:
            pass
        super().closeEvent(event)


def main():
    app = QtWidgets.QApplication(sys.argv)
    win = ControlPanel()
    win.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    # If started with server flag or env, run the server (no GUI)
    if ('--server' in sys.argv) or (os.environ.get('GAMEPAD_OSC_RUN_MODE') == 'server'):
        # Call the server entry directly to avoid import path issues in onefile
        try:
            from app.main import run_server
        except Exception:
            # Adjust sys.path for frozen bundle or source
            base_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
            if base_dir not in sys.path:
                sys.path.insert(0, base_dir)
            from app.main import run_server
        run_server(os.environ.get('LOG_LEVEL') or None)
    else:
        main()


