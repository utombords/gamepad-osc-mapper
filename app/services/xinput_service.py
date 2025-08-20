"""XInput-specific service abstraction.

Wraps the optional `XInput` Python package, providing connection status,
normalized inputs, deadzone/curve handling, simple rumble, and battery info
polling. Falls back to a dummy implementation when the package is unavailable.
"""
import logging
import ctypes 
from dataclasses import dataclass
import math
import threading 
import time # For polling loop sleep
from typing import Dict, Optional, Callable, Tuple, List, Any

logger = logging.getLogger(__name__)

# --- XInput Handling (Moved from input_service.py) ---
XINPUT_AVAILABLE = False
XInput = None
class _DummyXInput:
    @staticmethod
    def get_connected(): return [False, False, False, False]
    @staticmethod
    def get_state(user_index):
        class DummyState:
            pass
        return DummyState()
    @staticmethod
    def get_button_values(state): return {}
    @staticmethod
    def get_trigger_values(state): return (0.0, 0.0)
    @staticmethod
    def get_thumb_values(state): return ((0.0,0.0),(0.0,0.0))
    @staticmethod
    def set_deadzone(zone_id, value): pass
    @staticmethod
    def get_battery_information(user_index): return ("DISCONNECTED", "EMPTY")
    @staticmethod
    def set_vibration(user_index, left_motor, right_motor): pass
    DEADZONE_LEFT_THUMB = 0; DEADZONE_RIGHT_THUMB = 1; DEADZONE_TRIGGER = 2
    LEFT = 0; RIGHT = 1
    EVENT_CONNECTED = 0; EVENT_DISCONNECTED = 1; EVENT_BUTTON_PRESSED = 2
    EVENT_BUTTON_RELEASED = 3; EVENT_TRIGGER_MOVED = 4; EVENT_STICK_MOVED = 5
    class XInputNotConnectedError(Exception): pass

try:
    import XInput as RealXInput
    XInput = RealXInput
    if hasattr(XInput, 'get_connected') and hasattr(XInput, 'get_state'): XINPUT_AVAILABLE = True
    else: XInput = _DummyXInput(); XINPUT_AVAILABLE = False
except ImportError: XInput = _DummyXInput(); XINPUT_AVAILABLE = False
except Exception: XInput = _DummyXInput(); XINPUT_AVAILABLE = False
# --- End XInput Handling ---

# --- XINPUT RUMBLE CONSTANTS ---
XINPUT_RUMBLE_LEFT_MOTOR_INTENSITY = 0.8
XINPUT_RUMBLE_RIGHT_MOTOR_INTENSITY = 0.8
XINPUT_RUMBLE_PULSE_DURATION_S = 0.15
XINPUT_RUMBLE_PAUSE_DURATION_S = 0.1
XINPUT_RUMBLE_REPETITIONS = 1
# --- END XINPUT RUMBLE CONSTANTS ---

@dataclass
class DeadzoneConfig:
    stick_deadzone: float = 0.1
    trigger_deadzone: float = 0.1
    stick_curve: float = 1.0

def apply_stick_curve(value: float, curve: float) -> float:
    if curve == 1.0 or value == 0.0: return value
    sign = 1.0 if value > 0 else -1.0
    abs_val = min(abs(value), 1.0)
    return sign * pow(abs_val, curve)
# --- END DATACLASSES AND HELPERS ---

XINPUT_BUTTON_NAMES_LIST = [
    "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT", "START", "BACK",
    "LEFT_THUMB", "RIGHT_THUMB", "LEFT_SHOULDER", "RIGHT_SHOULDER", "A", "B", "X", "Y"
]
_XINPUT_BUTTON_SET_INTERNAL = set(XINPUT_BUTTON_NAMES_LIST)

class XInputService:
    """Manage XInput controllers and forward normalized events to InputService."""
    def __init__(self, main_input_service_instance, config_service_instance):
        self.main_input_service = main_input_service_instance
        self.config_service = config_service_instance
        self.logger = logger
        self.xinput_available = XINPUT_AVAILABLE
        self.deadzone_config = DeadzoneConfig()
        self.connected = [False] * 4
        self.button_states = [{name: False for name in XINPUT_BUTTON_NAMES_LIST} for _ in range(4)]
        self.trigger_states = [(0.0, 0.0) for _ in range(4)]
        self.thumb_states = [(0.0, 0.0, 0.0, 0.0) for _ in range(4)]
        self.battery_states: List[Tuple[Optional[str], Optional[str]]] = [(None, None)] * 4
        self.last_battery_check_time = [0.0] * 4
        self.battery_check_interval_s = 30.0 # Default, updated from settings
        self.polling_rate_hz = 120.0 # Default, updated from settings

        self.rumble_threads: Dict[int, threading.Thread] = {}
        self.rumble_stop_events: Dict[int, threading.Event] = {}

        self.polling_thread: Optional[threading.Thread] = None
        self._stop_event: Optional[threading.Event] = None
        self.is_running = False
        
        # Constants for rumble sequence - can be made configurable if needed
        self.XINPUT_RUMBLE_LEFT_MOTOR_INTENSITY = XINPUT_RUMBLE_LEFT_MOTOR_INTENSITY
        self.XINPUT_RUMBLE_RIGHT_MOTOR_INTENSITY = XINPUT_RUMBLE_RIGHT_MOTOR_INTENSITY
        self.XINPUT_RUMBLE_PULSE_DURATION_S = XINPUT_RUMBLE_PULSE_DURATION_S
        self.XINPUT_RUMBLE_PAUSE_DURATION_S = XINPUT_RUMBLE_PAUSE_DURATION_S
        self.XINPUT_RUMBLE_REPETITIONS = XINPUT_RUMBLE_REPETITIONS

        self.update_settings(self.main_input_service.input_settings) # Get initial settings
        self.logger.info(f"XInputService Initialized. XInput available = {self.xinput_available}")

    def update_settings(self, input_settings: Dict[str, Any]):
        """Apply input settings (deadzones/curve/rates) and configure XInput."""
        self.deadzone_config.stick_deadzone = float(input_settings.get('stick_deadzone', 0.1))
        self.deadzone_config.trigger_deadzone = float(input_settings.get('trigger_deadzone', 0.1))
        
        stick_curve_setting = input_settings.get('stick_curve', 1.0) # Default to 1.0 (linear)
        if isinstance(stick_curve_setting, str):
            if stick_curve_setting.lower() == 'linear':
                self.deadzone_config.stick_curve = 1.0
            else:
                try:
                    # Try to convert other strings if they represent numbers
                    self.deadzone_config.stick_curve = float(stick_curve_setting)
                except ValueError:
                    self.logger.warning(f"Invalid string value '{stick_curve_setting}' for stick_curve. Defaulting to 1.0 (linear).")
                    self.deadzone_config.stick_curve = 1.0
        elif isinstance(stick_curve_setting, (int, float)):
            self.deadzone_config.stick_curve = float(stick_curve_setting)
        else:
            self.logger.warning(f"Invalid type '{type(stick_curve_setting)}' for stick_curve. Defaulting to 1.0 (linear).")
            self.deadzone_config.stick_curve = 1.0

        self.battery_check_interval_s = float(input_settings.get('xinput_battery_check_interval_s', 30.0))
        self.polling_rate_hz = abs(float(input_settings.get('polling_rate_hz', 120.0)))
        if self.polling_rate_hz == 0: self.polling_rate_hz = 1.0

        if self.xinput_available and XInput:
            try:
                stick_dz_val = self.deadzone_config.stick_deadzone
                trigger_dz_val = self.deadzone_config.trigger_deadzone
                xinput_left_thumb_dz_int = int(stick_dz_val * 32767) 
                xinput_right_thumb_dz_int = int(stick_dz_val * 32767)
                xinput_trigger_deadzone_normalized = max(0.0, min(1.0, trigger_dz_val))
                xinput_trigger_dz_int = int(xinput_trigger_deadzone_normalized * 255)
                XInput.set_deadzone(XInput.DEADZONE_LEFT_THUMB, xinput_left_thumb_dz_int)
                XInput.set_deadzone(XInput.DEADZONE_RIGHT_THUMB, xinput_right_thumb_dz_int)
                XInput.set_deadzone(XInput.DEADZONE_TRIGGER, xinput_trigger_dz_int)
            except Exception as e: self.logger.error(f"XInputService: Error setting XInput deadzones: {e}")

    def start_polling(self):
        """Start the XInput event polling thread if XInput is available."""
        if not self.is_running and self.xinput_available:
            self.is_running = True
            self._stop_event = threading.Event()
            self.polling_thread = threading.Thread(target=self._xinput_polling_loop, daemon=True)
            self.polling_thread.start()
            self.logger.info("XInputService polling thread started.")
        elif not self.xinput_available:
            self.logger.info("XInputService: XInput not available, polling not started.")
        else: self.logger.warning("XInputService: Polling thread already running.")

    def stop_polling(self):
        """Stop the polling thread and ensure vibration is turned off."""
        if self.is_running:
            self.is_running = False
            if self._stop_event: self._stop_event.set()
            if self.polling_thread and self.polling_thread.is_alive():
                try: self.polling_thread.join(timeout=1.0)
                except Exception as e: self.logger.error(f"Error joining XInput polling thread: {e}")
                if self.polling_thread.is_alive(): self.logger.warning("XInput polling thread did not exit cleanly.")
                else: self.logger.info("XInput polling thread joined.")
            self.polling_thread = None
            self._stop_event = None
            # Ensure any active rumbles are stopped
            for i in range(4):
                 if i in self.rumble_stop_events and self.rumble_stop_events[i]: self.rumble_stop_events[i].set()
                 if self.connected[i] and XInput and hasattr(XInput, 'set_vibration'): 
                    try: XInput.set_vibration(i, 0, 0)
                    except: pass # Ignore errors on cleanup
            self.logger.info("XInputService polling stopped.")
        else: self.logger.warning("XInputService: Polling not running.")

    def _xinput_polling_loop(self):
        """Main loop fetching XInput events, normalizing, and forwarding them."""
        self.logger.info("XInputService polling loop started.")
        polling_interval = 1.0 / self.polling_rate_hz

        while self._stop_event and not self._stop_event.is_set():
            current_loop_start_time = time.monotonic()
            if not XInput: continue # Should not happen if xinput_available is true

            try:
                events = XInput.get_events()
                for event in events:
                    if self._stop_event and self._stop_event.is_set(): break
                    user_index = event.user_index
                    controller_id = f"xinput_{user_index}"

                    if event.type == XInput.EVENT_CONNECTED:
                        if not self.connected[user_index]:
                            self.connected[user_index] = True
                            for btn_name in XINPUT_BUTTON_NAMES_LIST: self.button_states[user_index][btn_name] = False
                            self.trigger_states[user_index] = (0.0, 0.0); self.thumb_states[user_index] = (0.0,0.0,0.0,0.0)
                            if self.main_input_service: self.main_input_service._notify_connect_listeners(controller_id, "XInput Controller", {'user_index': user_index, 'source': 'xinput_event_connect'})
                            if self.main_input_service.socketio: self.main_input_service.socketio.emit('xinput_device_update', {'status': 'connected', 'id': controller_id, 'user_index': user_index, 'type': 'XInput Controller'})
                            try: # Battery check on connect
                                battery_info = XInput.get_battery_information(user_index)
                                self.battery_states[user_index] = battery_info
                                if self.main_input_service: self.main_input_service._notify_battery_listeners(controller_id, battery_info)
                            except Exception: self.battery_states[user_index] = ("UNKNOWN", "ERROR_CONNECT")
                            self.last_battery_check_time[user_index] = current_loop_start_time
                    elif event.type == XInput.EVENT_DISCONNECTED:
                        if self.connected[user_index]:
                            self.connected[user_index] = False
                            for btn_name in XINPUT_BUTTON_NAMES_LIST: self.button_states[user_index][btn_name] = False
                            self.trigger_states[user_index] = (0.0,0.0); self.thumb_states[user_index] = (0.0,0.0,0.0,0.0)
                            self.battery_states[user_index] = (None, None)
                            if self.main_input_service: self.main_input_service._handle_xinput_disconnect_logic(user_index, controller_id, reason="event_disconnected") # Notify InputService to call its listeners
                    elif event.type == XInput.EVENT_BUTTON_PRESSED:
                        button_name = event.button
                        if button_name in _XINPUT_BUTTON_SET_INTERNAL and not self.button_states[user_index].get(button_name, False):
                            self.button_states[user_index][button_name] = True
                            if self.main_input_service: self.main_input_service._notify_input_listeners(controller_id, button_name, 1.0)
                    elif event.type == XInput.EVENT_BUTTON_RELEASED:
                        button_name = event.button
                        if button_name in _XINPUT_BUTTON_SET_INTERNAL and self.button_states[user_index].get(button_name, False):
                            self.button_states[user_index][button_name] = False
                            if self.main_input_service: self.main_input_service._notify_input_listeners(controller_id, button_name, 0.0)
                    elif event.type == XInput.EVENT_TRIGGER_MOVED:
                        value = event.value; trigger_id_str = "LEFT_TRIGGER" if event.trigger == XInput.LEFT else "RIGHT_TRIGGER"
                        current_lt, current_rt = self.trigger_states[user_index]; new_lt, new_rt = current_lt, current_rt
                        if event.trigger == XInput.LEFT: new_lt = value
                        else: new_rt = value
                        if new_lt != current_lt or new_rt != current_rt:
                            self.trigger_states[user_index] = (new_lt, new_rt)
                            if self.main_input_service: self.main_input_service._notify_input_listeners(controller_id, trigger_id_str, value)
                    elif event.type == XInput.EVENT_STICK_MOVED:
                        raw_x, raw_y = event.x, event.y
                        curved_x = apply_stick_curve(raw_x, self.deadzone_config.stick_curve)
                        curved_y = apply_stick_curve(raw_y, self.deadzone_config.stick_curve)
                        stick_x_id_str = "LEFT_STICK_X" if event.stick == XInput.LEFT else "RIGHT_STICK_X"
                        stick_y_id_str = "LEFT_STICK_Y" if event.stick == XInput.LEFT else "RIGHT_STICK_Y"
                        current_lx, current_ly, current_rx, current_ry = self.thumb_states[user_index]; new_lx, new_ly, new_rx, new_ry = current_lx, current_ly, current_rx, current_ry
                        if event.stick == XInput.LEFT: new_lx, new_ly = curved_x, curved_y
                        else: new_rx, new_ry = curved_x, curved_y
                        if new_lx != current_lx or new_ly != current_ly or new_rx != current_rx or new_ry != current_ry:
                            self.thumb_states[user_index] = (new_lx, new_ly, new_rx, new_ry)
                            if self.main_input_service:
                                if event.stick == XInput.LEFT:
                                    if new_lx != current_lx: self.main_input_service._notify_input_listeners(controller_id, stick_x_id_str, new_lx)
                                    if new_ly != current_ly: self.main_input_service._notify_input_listeners(controller_id, stick_y_id_str, new_ly)
                                else: # RIGHT_STICK
                                    if new_rx != current_rx: self.main_input_service._notify_input_listeners(controller_id, stick_x_id_str, new_rx)
                                    if new_ry != current_ry: self.main_input_service._notify_input_listeners(controller_id, stick_y_id_str, new_ry)
                # Periodic battery check
                for i in range(4):
                    if self.connected[i] and (current_loop_start_time - self.last_battery_check_time[i] > self.battery_check_interval_s):
                        cid_check = f"xinput_{i}"
                        try:
                            batt_info = XInput.get_battery_information(i)
                            if self.battery_states[i] != batt_info:
                                self.battery_states[i] = batt_info
                                if self.main_input_service: self.main_input_service._notify_battery_listeners(cid_check, batt_info)
                        except XInput.XInputNotConnectedError:
                            if self.connected[i]: # Was connected, now not
                                self.connected[i] = False # Update state
                                # ... (clear other states like buttons, triggers, thumbs if necessary) ...
                                if self.main_input_service: self.main_input_service._handle_xinput_disconnect_logic(i, cid_check, reason="disconnected_on_battery_check")
                        except Exception as e: self.logger.error(f"XInputService: Error getting C{i} battery: {e}")
                        self.last_battery_check_time[i] = current_loop_start_time
            except AttributeError as e: # Handle if XInput module (or dummy) is missing get_events
                if "XInput" in str(e) and "get_events" in str(e): self.xinput_available = False # Stop trying
                self.logger.error(f"XInputService: AttributeError in XInput event processing: {e}")
            except Exception as e: self.logger.error(f"XInputService: Error processing XInput events: {e}", exc_info=True)

            elapsed = time.monotonic() - current_loop_start_time
            sleep_dur = polling_interval - elapsed
            if sleep_dur > 0: time.sleep(sleep_dur)
            else: time.sleep(0.000001)
        self.logger.info("XInputService polling loop stopped.")

    def _execute_xinput_rumble_sequence(self, user_index: int):
        """Execute a rumble sequence on the specified XInput controller."""
        if not (0 <= user_index < 4 and self.connected[user_index]): return
        stop_event = self.rumble_stop_events.get(user_index)
        if not stop_event: self.logger.error(f"Rumble C{user_index}: No stop event."); return
        if not XInput: return

        try:
            for i in range(self.XINPUT_RUMBLE_REPETITIONS):
                if stop_event.is_set() or not self.is_running or not self.connected[user_index]: break
                XInput.set_vibration(user_index, self.XINPUT_RUMBLE_LEFT_MOTOR_INTENSITY, self.XINPUT_RUMBLE_RIGHT_MOTOR_INTENSITY)
                time.sleep(self.XINPUT_RUMBLE_PULSE_DURATION_S)
                if stop_event.is_set() or not self.is_running or not self.connected[user_index]: break
                XInput.set_vibration(user_index, 0, 0)
                if i < self.XINPUT_RUMBLE_REPETITIONS - 1: time.sleep(self.XINPUT_RUMBLE_PAUSE_DURATION_S)
        except XInput.XInputNotConnectedError:
            if self.connected[user_index]: # If still marked connected, handle disconnect
                self.connected[user_index] = False
                if self.main_input_service: self.main_input_service._handle_xinput_disconnect_logic(user_index, f"xinput_{user_index}", "disconnected_during_rumble")
        except Exception as e: self.logger.error(f"XInputService: Error in rumble C{user_index}: {e}")
        finally:
            try: XInput.set_vibration(user_index, 0, 0) # Ensure vibration is off
            except: pass # Ignore errors on final off attempt
            if user_index in self.rumble_threads: del self.rumble_threads[user_index]
            if user_index in self.rumble_stop_events: del self.rumble_stop_events[user_index]

    def trigger_xinput_rumble(self, user_index: int, repetitions: Optional[int] = None, 
                              pulse_duration_s: Optional[float] = None, pause_duration_s: Optional[float] = None, 
                              left_intensity: Optional[float] = None, right_intensity: Optional[float] = None) -> bool:
        """Trigger a rumble sequence on the specified XInput controller if connected."""
        # This method now directly calls _execute_xinput_rumble_sequence (which is now part of this class)
        if not self.xinput_available or not XInput: return False
        if not (0 <= user_index < 4 and self.connected[user_index]): return False

        if user_index in self.rumble_threads and self.rumble_threads[user_index].is_alive():
            if self.rumble_stop_events.get(user_index): self.rumble_stop_events[user_index].set()
        
        # TODO: Allow custom rumble parameters to be passed to _execute_xinput_rumble_sequence if needed
        # For now, _execute_xinput_rumble_sequence uses class constants for rumble params.

        self.rumble_stop_events[user_index] = threading.Event()
        thread = threading.Thread(target=self._execute_xinput_rumble_sequence, args=(user_index,))
        thread.daemon = True
        self.rumble_threads[user_index] = thread
        thread.start()
        return True

    # ... other XInput specific methods can go here