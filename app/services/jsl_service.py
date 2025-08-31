"""
JoyShockLibrary (JSL) integration
---------------------------------

This module encapsulates all interaction with JoyShockLibrary to support
controllers such as Nintendo Switch Pro, Joy‑Con (L/R), Sony DualShock 4,
and Sony DualSense. It abstracts device discovery, connection lifecycle,
state polling (buttons, triggers, sticks), optional IMU (accelerometer/gyro),
and forwards normalized generic input events to the main InputService.

Design highlights:
- Thin ctypes layer with explicit prototypes for JSL functions we use
  (kept defensive with try/except where symbols may be absent).
- Non‑blocking high‑rate polling thread; device rescans run in a separate
  background worker to avoid stalling the polling loop.
- Thread‑safe device registry guarded by a lock; disconnects funneled
  through a queue to avoid callback threading issues.
- Normalization to generic input names occurs before notifying InputService
  so the rest of the app remains device‑agnostic.
"""
import logging
import enum
import ctypes
import os
import threading
import queue
import time
from typing import Dict, Optional, Callable, Tuple, List, Any

logger = logging.getLogger(__name__)

# --- JSL constants and C interop structures ---
class JSL_TYPE(enum.IntEnum):
    JS_TYPE_JOYCON_LEFT = 1
    JS_TYPE_JOYCON_RIGHT = 2
    JS_TYPE_PRO_CONTROLLER = 3
    JS_TYPE_DS4 = 4
    JS_TYPE_DS = 5

# Button bitmasks as defined by JoyShockLibrary (subset used by this app)
class JSL_BUTTON_MASKS(enum.IntFlag):
    JSMASK_UP = 0x00001
    JSMASK_DOWN = 0x00002
    JSMASK_LEFT = 0x00004
    JSMASK_RIGHT = 0x00008
    JSMASK_PLUS = 0x00010 # Options on DS4/DS
    JSMASK_MINUS = 0x00020 # Share on DS4/DS
    JSMASK_LCLICK = 0x00040
    JSMASK_RCLICK = 0x00080
    JSMASK_L = 0x00100
    JSMASK_R = 0x00200
    JSMASK_ZL = 0x00400 # L2 on DS4/DS
    JSMASK_ZR = 0x00800 # R2 on DS4/DS
    JSMASK_S = 0x01000 # Triangle on DS4/DS
    JSMASK_E = 0x02000 # Circle on DS4/DS
    JSMASK_W = 0x04000 # Square on DS4/DS
    JSMASK_N = 0x08000 # Cross on DS4/DS
    JSMASK_HOME = 0x10000 # PS button
    JSMASK_CAPTURE = 0x20000 # Touchpad click on DS4/DS, Capture on Switch
    JSMASK_MIC = 0x040000 # DS5 specific
    JSMASK_SL = 0x080000 # JoyCon specific
    JSMASK_SR = 0x100000 # JoyCon specific
    JSMASK_FNL = 0x200000 # DS5 specific
    JSMASK_FNR = 0x400000 # DS5 specific

# Map button masks to our generic input names
jsl_button_mask_to_name = {
    JSL_BUTTON_MASKS.JSMASK_UP: "UP",
    JSL_BUTTON_MASKS.JSMASK_DOWN: "DOWN",
    JSL_BUTTON_MASKS.JSMASK_LEFT: "LEFT",
    JSL_BUTTON_MASKS.JSMASK_RIGHT: "RIGHT",
    JSL_BUTTON_MASKS.JSMASK_PLUS: "PLUS", # Or OPTIONS
    JSL_BUTTON_MASKS.JSMASK_MINUS: "MINUS", # Or SHARE
    JSL_BUTTON_MASKS.JSMASK_LCLICK: "LEFT_STICK_PRESS",
    JSL_BUTTON_MASKS.JSMASK_RCLICK: "RIGHT_STICK_PRESS",
    JSL_BUTTON_MASKS.JSMASK_L: "LEFT_SHOULDER",
    JSL_BUTTON_MASKS.JSMASK_R: "RIGHT_SHOULDER",
    JSL_BUTTON_MASKS.JSMASK_ZL: "LEFT_TRIGGER_PRESS", # For digital press of ZL/ZR
    JSL_BUTTON_MASKS.JSMASK_ZR: "RIGHT_TRIGGER_PRESS", # For digital press of ZL/ZR
    JSL_BUTTON_MASKS.JSMASK_N: "N", # Cross / A
    JSL_BUTTON_MASKS.JSMASK_E: "E", # Circle / B
    JSL_BUTTON_MASKS.JSMASK_W: "W", # Square / X
    JSL_BUTTON_MASKS.JSMASK_S: "S", # Triangle / Y
    JSL_BUTTON_MASKS.JSMASK_HOME: "HOME", # PS / HOME
    JSL_BUTTON_MASKS.JSMASK_CAPTURE: "CAPTURE", # TOUCHPAD_CLICK / CAPTURE
    JSL_BUTTON_MASKS.JSMASK_MIC: "MIC",
    JSL_BUTTON_MASKS.JSMASK_SL: "SL",
    JSL_BUTTON_MASKS.JSMASK_SR: "SR",
    JSL_BUTTON_MASKS.JSMASK_FNL: "FNL",
    JSL_BUTTON_MASKS.JSMASK_FNR: "FNR",
}

class JOY_SHOCK_STATE(ctypes.Structure):
    """C struct representing a subset of JoyShockLibrary's simple state.

    Fields match the ABI expected by JslGetSimpleState.
    """
    _fields_ = [
        ("buttons", ctypes.c_int),
        ("lTrigger", ctypes.c_float),
        ("rTrigger", ctypes.c_float),
        ("stickLX", ctypes.c_float),
        ("stickLY", ctypes.c_float),
        ("stickRX", ctypes.c_float),
        ("stickRY", ctypes.c_float),
    ]

class IMU_STATE(ctypes.Structure):
    """C struct representing IMU state (accelerometer and gyroscope)."""
    _fields_ = [
        ("accelX", ctypes.c_float),
        ("accelY", ctypes.c_float),
        ("accelZ", ctypes.c_float),
        ("gyroX", ctypes.c_float),
        ("gyroY", ctypes.c_float),
        ("gyroZ", ctypes.c_float),
    ]

# Callback signatures exposed by JoyShockLibrary. The connect callback provides
# only the device handle; the disconnect callback provides handle and a flag
# indicating whether the disconnect was a timeout.
CONNECT_CALLBACK = ctypes.CFUNCTYPE(None, ctypes.c_int)
DISCONNECT_CALLBACK = ctypes.CFUNCTYPE(None, ctypes.c_int, ctypes.c_bool)

def get_jsl_type_string(jsl_type_enum):
    """Return a friendly string for a JSL controller type enum value.

    Accepts either our local JSL_TYPE enum or the raw int from the DLL.
    """
    if isinstance(jsl_type_enum, JSL_TYPE): # If it's already our enum
        return jsl_type_enum.name.replace("JS_TYPE_", "").replace("_", " ")
    try:
        return JSL_TYPE(jsl_type_enum).name.replace("JS_TYPE_", "").replace("_", " ")
    except ValueError:
        return f"Unknown JSL Type ({jsl_type_enum})"
# --- End JSL Constants and Structures ---

class JSLService:
    """Service wrapping JoyShockLibrary usage.

    Responsibilities:
    - Load the DLL, set up prototypes and callbacks
    - Track connected devices and their last-known states
    - Poll at high rate and notify InputService on changes
    - Run device rescans in the background

    Threading:
    - A dedicated polling thread (`_jsl_polling_loop`)
    - Optional background rescan worker (`_rescan_worker`)
    - Device registry protected by `jsl_devices_lock`
    """
    def __init__(self, main_input_service_instance, config_service_instance):
        self.main_input_service = main_input_service_instance # To call back for events
        self.config_service = config_service_instance
        self.logger = logger

        # JSL state
        self.jsl: Optional[ctypes.WinDLL] = None # Type hint for clarity
        self.jsl_devices: Dict[int, Dict[str, Any]] = {} 
        self.jsl_devices_lock = threading.Lock() 
        self.previous_jsl_states: Dict[str, Dict[str, Any]] = {} 
        # DLL path: app/lib/JoyShockLibrary.dll (relative to this file)
        self.jsl_dll_path = os.path.join(os.path.dirname(__file__), '..', 'lib', 'JoyShockLibrary.dll')
        self._jsl_connect_cb_ref: Optional[CONNECT_CALLBACK] = None 
        self._jsl_disconnect_cb_ref: Optional[DISCONNECT_CALLBACK] = None 
        self.jsl_subsystem_potentially_unrecoverable = False
        self.jsl_disconnect_queue: queue.Queue = queue.Queue()
        self.jsl_available = False # Will be set after attempting to load
        self.jsl_rescan_interval_s = 5.0  # Updated from config
        self.jsl_rescan_polling = True    # Updated from config
        self.polling_rate_hz = 120.0      # Updated from input_settings

        self.polling_thread: Optional[threading.Thread] = None
        self._stop_event: Optional[threading.Event] = None
        self.is_running = False
        self.JSL_STANDARD_INPUT_NAMES = self.main_input_service.JSL_STANDARD_INPUT_NAMES # Get from main service

        # Background rescan management to avoid blocking the high-rate polling loop
        self._rescan_thread: Optional[threading.Thread] = None
        self._rescan_in_progress: bool = False
        self._rescan_lock = threading.Lock()

        self._initialize_jsl_library()
        self.update_settings(self.main_input_service.input_settings) # Get initial settings
        self.logger.info(f"JSL ready (available={self.jsl_available})")

    def update_settings(self, input_settings: Dict[str, Any]):
        """Apply updated input-related settings relevant to JSL.

        Recognized keys:
        - jsl_rescan_interval_s (float > 0): how often to attempt device rescans
        - jsl_rescan_polling (bool): whether periodic rescans are enabled
        - polling_rate_hz (float > 0): main JSL polling frequency
        """
        self.jsl_rescan_interval_s = abs(float(input_settings.get('jsl_rescan_interval_s', 5.0)))
        if self.jsl_rescan_interval_s == 0: self.jsl_rescan_interval_s = 1
        self.logger.debug(f"jsl_rescan_interval_s={self.jsl_rescan_interval_s}s")

        # Read and update jsl_rescan_polling
        raw_rescan_polling = input_settings.get('jsl_rescan_polling', True)
        if isinstance(raw_rescan_polling, bool):
            self.jsl_rescan_polling = raw_rescan_polling
        elif isinstance(raw_rescan_polling, str):
            self.jsl_rescan_polling = raw_rescan_polling.lower() == 'true'
        else:
            self.jsl_rescan_polling = True # Default to True if type is unexpected
        self.logger.debug(f"jsl_rescan_polling={self.jsl_rescan_polling}")
        
        self.polling_rate_hz = abs(float(input_settings.get('polling_rate_hz', 120.0)))
        if self.polling_rate_hz == 0: self.polling_rate_hz = 1.0
        self.logger.debug(f"polling_rate_hz={self.polling_rate_hz}")

    def _initialize_jsl_library(self):
        """Load DLL and set up prototypes and callbacks if available."""
        self._load_jsl()
        self.jsl_available = bool(self.jsl)
        if self.jsl_available:
            self._setup_jsl_prototypes()
            self._init_jsl_callbacks()
        else:
            self.logger.warning("JSL library not available. JSL features will be disabled.")

    def _load_jsl(self):
        """Attempt to load JoyShockLibrary.dll from the expected path."""
        try:
            self.jsl = ctypes.WinDLL(self.jsl_dll_path)
            self.logger.info("JSL DLL loaded")
        except Exception as e:
            self.logger.error(f"Failed to load JoyShockLibrary.dll from {self.jsl_dll_path}: {e}")
            self.jsl = None

    def _setup_jsl_prototypes(self):
        """Declare ctypes prototypes for JSL functions used by this service."""
        if not self.jsl: return

        self.jsl.JslConnectDevices.argtypes = []
        self.jsl.JslConnectDevices.restype = ctypes.c_int

        self.jsl.JslGetConnectedDeviceHandles.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_int]
        self.jsl.JslGetConnectedDeviceHandles.restype = ctypes.c_int

        self.jsl.JslDisconnectAndDisposeAll.argtypes = []
        self.jsl.JslDisconnectAndDisposeAll.restype = None

        try:
            self.jsl.JslDisconnectDevice.argtypes = [ctypes.c_int]
            self.jsl.JslDisconnectDevice.restype = ctypes.c_bool
            self.logger.debug("Loaded JslDisconnectDevice")
        except AttributeError:
            self.logger.warning("JslDisconnectDevice function not found in the loaded JoyShockLibrary.dll.")

        self.jsl.JslStillConnected.argtypes = [ctypes.c_int]
        self.jsl.JslStillConnected.restype = ctypes.c_bool

        self.jsl.JslGetSimpleState.argtypes = [ctypes.c_int]
        self.jsl.JslGetSimpleState.restype = JOY_SHOCK_STATE

        self.jsl.JslGetIMUState.argtypes = [ctypes.c_int]
        self.jsl.JslGetIMUState.restype = IMU_STATE
        
        self.jsl.JslSetConnectCallback.argtypes = [CONNECT_CALLBACK]
        self.jsl.JslSetConnectCallback.restype = None
        
        self.jsl.JslSetDisconnectCallback.argtypes = [DISCONNECT_CALLBACK]
        self.jsl.JslSetDisconnectCallback.restype = None
        
        try:
            self.jsl.JslGetControllerType.argtypes = [ctypes.c_int]
            self.jsl.JslGetControllerType.restype = ctypes.c_int
        except AttributeError:
            self.logger.error("JslGetControllerType function not found. This is critical for JSL operation.")

        try:
            self.jsl.JslScanAndConnectNewDevices.argtypes = []
            self.jsl.JslScanAndConnectNewDevices.restype = ctypes.c_int
            self.logger.debug("Loaded JslScanAndConnectNewDevices")
        except AttributeError:
            self.logger.error("JslScanAndConnectNewDevices function not found in the loaded JoyShockLibrary.dll.")
            def _placeholder_scan_new():
                return 0
            if self.jsl:
                self.jsl.JslScanAndConnectNewDevices = _placeholder_scan_new

        # Define JslGetControllerSplitType
        self.jsl.JslGetControllerSplitType.argtypes = [ctypes.c_int]
        self.jsl.JslGetControllerSplitType.restype = ctypes.c_int

        self.logger.debug("JSL function prototypes set.")

    def _init_jsl_callbacks(self):
        """Register connect/disconnect callbacks with the DLL (if available)."""
        if not self.jsl: return
        self._jsl_connect_cb_ref = CONNECT_CALLBACK(self._on_jsl_connect_callback_handler) 
        self._jsl_disconnect_cb_ref = DISCONNECT_CALLBACK(self._on_jsl_disconnect_callback_handler)
        self.jsl.JslSetConnectCallback(self._jsl_connect_cb_ref)
        self.jsl.JslSetDisconnectCallback(self._jsl_disconnect_cb_ref)
        self.logger.debug("JSL callbacks registered")

    def _on_jsl_connect_callback_handler(self, handle: int):
        """Handle device connect callback; query type and notify InputService."""
        actual_type_enum = -1
        type_str = "Unknown (JslGetControllerType failed in callback)"

        if self.jsl:
            if hasattr(self.jsl, 'JslGetControllerType'):
                try:
                    actual_type_enum = self.jsl.JslGetControllerType(handle)
                    type_str = get_jsl_type_string(actual_type_enum)
                    self.logger.debug(f"JSL type: handle={handle} type_enum={actual_type_enum} ({type_str})")
                except Exception as e:
                    self.logger.error(f"JSLService _on_jsl_connect_callback_handler: Error calling JslGetControllerType for handle {handle}: {e}", exc_info=True)
            else:
                self.logger.warning("JSLService _on_jsl_connect_callback_handler: JslGetControllerType function not found in loaded JSL DLL.")

        else:
            self.logger.error("JSLService _on_jsl_connect_callback_handler: JSL library not loaded, cannot get controller type.")


        self.logger.debug("Notify InputService of JSL connect")
        
        # Pass the type enum obtained from JslGetControllerType to the InputService
        if self.main_input_service and hasattr(self.main_input_service, '_on_jsl_connect'):
            self.main_input_service._on_jsl_connect(handle, actual_type_enum)
        else:
            self.logger.error("JSLService: main_input_service not available or missing _on_jsl_connect method.")

    def _on_jsl_disconnect_callback_handler(self, handle, timed_out):
        """Handle device disconnect callback; enqueue cleanup and notify InputService."""
        self.logger.debug(f"JSL disconnect: handle={handle} timed_out={timed_out}")
        if self.main_input_service and hasattr(self.main_input_service, '_on_jsl_disconnect'):
            self.main_input_service._on_jsl_disconnect(handle, timed_out)
        else:
            self.logger.error("JSLService: main_input_service not available or missing _on_jsl_disconnect method.")

    def _ensure_jsl_device_entry(self, handle):
        """Ensure a basic dictionary structure exists for the given device handle."""
        if handle not in self.jsl_devices:
            self.jsl_devices[handle] = {
                'id_str': f"jsl_{handle}",
                'type_enum': -1, 
                'type_str': "Unknown JSL Device (Initial Entry)",
                'connected': False, 
                'error_logged': False, 
                'valid_device': False,
                'error_logged_imu': False
            }
            self.logger.debug(f"JSLService: Ensured JSL device entry for handle {handle}.")

    def _handle_jsl_disconnect_logic(self, handle, source="unknown_source"):
        """Disconnect a JSL device and clean up state.

        Returns the internal id string (e.g., 'jsl_5') for logging/upstream use.
        """
        internal_jsl_id_str = f"jsl_{handle}"
        self.logger.info(f"JSL disconnect {internal_jsl_id_str}")
        device_info_lost = None
        already_processed = False
        with self.jsl_devices_lock:
            if handle in self.jsl_devices:
                device_info_lost = self.jsl_devices.pop(handle, None)
                self.logger.debug(f"Removed {internal_jsl_id_str}; remaining={len(self.jsl_devices)}")
            else:
                already_processed = True
            
            if internal_jsl_id_str in self.previous_jsl_states: 
                del self.previous_jsl_states[internal_jsl_id_str]
                self.logger.debug(f"Removed prev state for {internal_jsl_id_str}")

        if device_info_lost:
            self.logger.debug(f"Processed disconnect {internal_jsl_id_str}")
            # Notification to main service listeners is handled by the main service itself after calling this.
            return internal_jsl_id_str # Return ID for main service to use for notification
        else:
            if already_processed:
                self.logger.debug(f"Disconnect already processed {internal_jsl_id_str}")
            else:
                self.logger.warning(f"JSLService: No existing device info found for handle {handle} ({source}) and not marked as already_processed.")
            return internal_jsl_id_str

    def start_polling(self):
        """Start the JSL polling loop (if library is available)."""
        if not self.is_running and self.jsl_available:
            self.is_running = True
            self._stop_event = threading.Event()
            self.polling_thread = threading.Thread(target=self._jsl_polling_loop, daemon=True)
            self.polling_thread.start()
            self.logger.info("Start JSL polling")
        elif not self.jsl_available:
            self.logger.warning("JSLService: JSL not available, cannot start polling.")
        else:
            self.logger.warning("JSLService: Polling thread already running.")

    def stop_polling(self):
        """Stop the polling loop and release JSL resources (best effort)."""
        if self.is_running:
            self.is_running = False
            if self._stop_event: self._stop_event.set()
            if self.polling_thread and self.polling_thread.is_alive():
                try: self.polling_thread.join(timeout=1.0)
                except Exception as e: self.logger.error(f"Error joining JSL polling thread: {e}")
                if self.polling_thread.is_alive(): self.logger.warning("JSL polling thread did not exit cleanly.")
                else: self.logger.debug("JSL polling thread joined")
            self.polling_thread = None
            self._stop_event = None
            if self.jsl and hasattr(self.jsl, 'JslDisconnectAndDisposeAll'):
                try: self.jsl.JslDisconnectAndDisposeAll(); self.logger.debug("JSL DisconnectAndDisposeAll called")
                except Exception as e: self.logger.error(f"Error in JslDisconnectAndDisposeAll: {e}")
            with self.jsl_devices_lock: self.jsl_devices.clear(); self.previous_jsl_states.clear()
            self.logger.info("Stop JSL polling")
        else: self.logger.warning("JSLService: Polling not running.")

    def _jsl_polling_loop(self):
        """High‑rate polling loop: emit input changes and manage rescans."""
        self.logger.info("JSL loop start")
        # Schedule an early rescan without blocking the loop
        if self.jsl and hasattr(self.jsl, 'JslScanAndConnectNewDevices'):
            self._schedule_rescan()

        last_jsl_rescan_time = time.monotonic() - max(0.0, self.jsl_rescan_interval_s - 0.5)
        polling_interval = 1.0 / self.polling_rate_hz

        while self._stop_event and not self._stop_event.is_set():
            loop_start_time = time.monotonic()

            # Process pending disconnects from callback thread(s)
            try:
                while not self.jsl_disconnect_queue.empty():
                    disconnect_event = self.jsl_disconnect_queue.get_nowait()
                    disconnected_id = self._handle_jsl_disconnect_logic(disconnect_event['handle'], source=disconnect_event['source'])
                    if disconnected_id and self.main_input_service: self.main_input_service._notify_disconnect_listeners(disconnected_id)
                    self.jsl_disconnect_queue.task_done()
            except queue.Empty: pass
            except Exception as e: self.logger.error(f"Error processing JSL disconnect queue in JSLService: {e}", exc_info=True)

            # Periodically rescan for new devices in the background
            if self.jsl_rescan_polling:
                if (loop_start_time - last_jsl_rescan_time > self.jsl_rescan_interval_s):
                    self._schedule_rescan()
                    last_jsl_rescan_time = loop_start_time
            
            # JSL State Polling for connected devices
            if self.jsl:
                active_handles = []
                with self.jsl_devices_lock: active_handles = [h for h, d in self.jsl_devices.items() if d.get('connected') and d.get('valid_device')]

                for handle in active_handles:
                    dev_id_str = f"jsl_{handle}"
                    try:
                        with self.jsl_devices_lock: # Re-check validity inside loop, though active_handles should be current
                            if not self.jsl_devices.get(handle, {}).get('valid_device'): continue
                        
                        if dev_id_str not in self.previous_jsl_states: self.previous_jsl_states[dev_id_str] = {}
                        current_state = {}
                        js_state = self.jsl.JslGetSimpleState(handle)

                        for mask_val, name in jsl_button_mask_to_name.items():
                            pressed = (js_state.buttons & mask_val) != 0
                            current_state[name] = 1.0 if pressed else 0.0
                            if self.previous_jsl_states[dev_id_str].get(name) != current_state[name] and self.main_input_service:
                                self.main_input_service._notify_input_listeners(dev_id_str, name, current_state[name])
                        
                        trigger_l_name = self.JSL_STANDARD_INPUT_NAMES["TRIGGER_L"]
                        current_state[trigger_l_name] = js_state.lTrigger
                        if self.previous_jsl_states[dev_id_str].get(trigger_l_name) != js_state.lTrigger and self.main_input_service:
                            self.main_input_service._notify_input_listeners(dev_id_str, trigger_l_name, js_state.lTrigger)

                        trigger_r_name = self.JSL_STANDARD_INPUT_NAMES["TRIGGER_R"]
                        current_state[trigger_r_name] = js_state.rTrigger
                        if self.previous_jsl_states[dev_id_str].get(trigger_r_name) != js_state.rTrigger and self.main_input_service:
                            self.main_input_service._notify_input_listeners(dev_id_str, trigger_r_name, js_state.rTrigger)

                        stick_inputs = [
                            (self.JSL_STANDARD_INPUT_NAMES["STICK_LX"], js_state.stickLX, 'stick'),
                            (self.JSL_STANDARD_INPUT_NAMES["STICK_LY"], -js_state.stickLY, 'stick'), # Invert Y
                            (self.JSL_STANDARD_INPUT_NAMES["STICK_RX"], js_state.stickRX, 'stick'),
                            (self.JSL_STANDARD_INPUT_NAMES["STICK_RY"], js_state.stickRY, 'stick')
                        ]
                        for name, raw_val, val_type_str in stick_inputs:
                            processed_val = self.main_input_service._apply_deadzone_and_curve(raw_val, val_type_str)
                            current_state[name] = processed_val
                            if self.previous_jsl_states[dev_id_str].get(name) != processed_val and self.main_input_service:
                                self.main_input_service._notify_input_listeners(dev_id_str, name, processed_val)

                        # IMU state (if available on this device type)
                        dev_type_enum = self.jsl_devices.get(handle, {}).get('type_enum')
                        if dev_type_enum in [JSL_TYPE.JS_TYPE_JOYCON_LEFT, JSL_TYPE.JS_TYPE_JOYCON_RIGHT, JSL_TYPE.JS_TYPE_PRO_CONTROLLER, JSL_TYPE.JS_TYPE_DS4, JSL_TYPE.JS_TYPE_DS]:
                            imu_s = self.jsl.JslGetIMUState(handle)
                            # Map IMU values to generic ACCEL_/GYRO_ axes (scaled/clamped where needed)
                            raw_imu_map = {
                                self.JSL_STANDARD_INPUT_NAMES["GYRO_X"]:  imu_s.accelX,
                                self.JSL_STANDARD_INPUT_NAMES["GYRO_Y"]:  imu_s.accelY,
                                self.JSL_STANDARD_INPUT_NAMES["GYRO_Z"]:  imu_s.accelZ,
                                self.JSL_STANDARD_INPUT_NAMES["ACCEL_X"]: imu_s.gyroX / 750.0,
                                self.JSL_STANDARD_INPUT_NAMES["ACCEL_Y"]: imu_s.gyroY / 750.0,
                                self.JSL_STANDARD_INPUT_NAMES["ACCEL_Z"]: imu_s.gyroZ / 750.0
                            }
                            for name, raw_val in raw_imu_map.items():
                                processed_val = self.main_input_service._apply_deadzone_and_curve(raw_val, 'motion') # Uses 'motion' type for deadzone
                                clamped_val = max(-1.0, min(1.0, processed_val))
                                current_state[name] = clamped_val
                                if self.previous_jsl_states[dev_id_str].get(name) != clamped_val and self.main_input_service:
                                    self.main_input_service._notify_input_listeners(dev_id_str, name, clamped_val)
                        
                        self.previous_jsl_states[dev_id_str] = current_state.copy()
                    except Exception as e:
                        self.logger.error(f"Error polling JSL device {dev_id_str}: {e}", exc_info=True)
                        # Optionally mark device as problematic or attempt recovery
            
            elapsed = time.monotonic() - loop_start_time
            polling_interval = 1.0 / self.polling_rate_hz # Recalculate in case it changed
            sleep_dur = polling_interval - elapsed
            if sleep_dur > 0: 
                time.sleep(sleep_dur)
            else: 
                # Iteration overran target interval; log occasionally to aid diagnostics
                self.logger.debug(f"JSL Polling Loop: Iteration took too long ({elapsed:.6f}s) > interval ({polling_interval:.6f}s).")
                time.sleep(0.000001) # Minimal sleep to prevent tight loop if processing takes too long
        
        self.logger.debug("JSL loop stopped")

    def _schedule_rescan(self):
        """Start a background JSL rescan if one is not already running."""
        with self._rescan_lock:
            if self._rescan_in_progress or not (self.jsl and hasattr(self.jsl, 'JslScanAndConnectNewDevices')):
                return
            self._rescan_in_progress = True
            self._rescan_thread = threading.Thread(target=self._rescan_worker, name="JSL_Rescan", daemon=True)
            self._rescan_thread.start()

    def _rescan_worker(self):
        """Background worker that invokes JslScanAndConnectNewDevices()."""
        try:
            # Call into the DLL; this may block briefly. Running in background avoids stalling polling.
            self.jsl.JslScanAndConnectNewDevices()
        except Exception as e:
            self.logger.error(f"Error during JSL rescan: {e}")
        finally:
            with self._rescan_lock:
                self._rescan_in_progress = False

    # ... other JSL specific methods will go here 