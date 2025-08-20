"""Unified input service for XInput and JoyShockLibrary (JSL).

Coordinates polling, device connect/disconnect events, and raw input updates
from sub-services. Normalizes values, exposes listener registration for other
services, and forwards configuration changes to sub-systems.
"""

import logging
import time
import threading
# import os  # Not directly used here; keep dependencies minimal in this module
import ctypes
# import queue  # Disconnect queueing is handled inside JSLService
# from dataclasses import dataclass  # XInput deadzone config is managed by XInputService
from typing import Dict, Optional, Callable, Tuple, List, Any
from ..utils.Singleton import Singleton
from .jsl_service import JSLService, get_jsl_type_string, JSL_TYPE, jsl_button_mask_to_name # Import JSL_TYPE, jsl_button_mask_to_name
from .xinput_service import XInputService, XINPUT_AVAILABLE as XINPUT_SERVICE_AVAILABLE
import math # Still needed for math.copysign

logger = logging.getLogger(__name__)
# Respect global logging configuration; default to INFO here
logger.setLevel(logging.INFO)


# --- JSL, XInput, Rumble Constants, DeadzoneConfig, apply_stick_curve all moved to respective services ---

class InputService(metaclass=Singleton):
    XINPUT_BUTTON_NAMES = [ 
        "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT",
        "START", "BACK",
        "LEFT_THUMB", "RIGHT_THUMB",
        "LEFT_SHOULDER", "RIGHT_SHOULDER",
        "A", "B", "X", "Y"
    ]
    _XINPUT_BUTTON_SET = set(XINPUT_BUTTON_NAMES)

    JSL_STANDARD_INPUT_NAMES = {
        "STICK_LX": "LEFT_STICK_X", "STICK_LY": "LEFT_STICK_Y",
        "STICK_RX": "RIGHT_STICK_X", "STICK_RY": "RIGHT_STICK_Y",
        "TRIGGER_L": "LEFT_TRIGGER", "TRIGGER_R": "RIGHT_TRIGGER",
        "ACCEL_X": "ACCEL_X", "ACCEL_Y": "ACCEL_Y", "ACCEL_Z": "ACCEL_Z",
        "GYRO_X": "GYRO_X", "GYRO_Y": "GYRO_Y", "GYRO_Z": "GYRO_Z",
    }

    def __init__(self, config_service_instance, socketio_instance=None):
        """Initialize input aggregation and sub-services.

        Reads input settings from configuration, sets thresholds for discrete
        actions, and prepares listener registries. Creates JSL and XInput
        sub-services and aligns their settings to the active configuration.
        """
        self.config_service = config_service_instance
        full_config = self.config_service.get_config()
        self.input_settings = full_config.get('input_settings', {})
        self.socketio = socketio_instance
        self.logger = logger

        self.jsl_service = JSLService(main_input_service_instance=self, config_service_instance=self.config_service)
        self.xinput_service = XInputService(main_input_service_instance=self, config_service_instance=self.config_service)

        self.listeners: List[Callable[[str, str, float], None]] = []
        self.connect_listeners: List[Callable[[str, str, Dict[str, Any]], None]] = [] 
        self.disconnect_listeners: List[Callable[[str], None]] = [] 
        self.battery_listeners: List[Callable[[str, Tuple[Optional[str], Optional[str]]], None]] = []

        # Threshold for treating an input as a "press" for discrete actions (buttons/triggers)
        # This is used by ChannelProcessingService for toggle/reset/step actions
        self.button_press_threshold: float = 0.5
        # Threshold to consider analog input as "active" movement for continuous keep-alive emitting (sticks/gyro/triggers)
        self.analog_activity_threshold: float = 0.02

        self.xinput_available = XINPUT_SERVICE_AVAILABLE # Get from xinput_service module
        self.jsl_available = self.jsl_service.jsl_available # Get from jsl_service instance

        self.polling_rate_hz = abs(self.input_settings.get('polling_rate_hz', 120))
        if self.polling_rate_hz == 0: 
            self.polling_rate_hz = 1 
            logger.warning("Polling rate was 0, set to 1 Hz to avoid issues.")

        self.reload_config() 

        self.logger.info(f"InputService Initialized. XINPUT_AVAILABLE = {self.xinput_available}. JSL available = {self.jsl_available}. Input settings: {self.input_settings}")
        
        self._main_polling_thread: Optional[threading.Thread] = None # Renamed to avoid confusion
        self._main_stop_event: Optional[threading.Event] = None   # Renamed
        self.is_running = False # Overall service running state

    def reload_config(self, new_input_settings=None):
        """Reload input settings and propagate them to sub-services."""
        if new_input_settings is not None:
            self.input_settings = new_input_settings
        else: 
            full_config = self.config_service.get_config()
            self.input_settings = full_config.get('input_settings', {})
        
        self.logger.info(f"InputService: Configuration reloaded. New input_settings: {self.input_settings}")
        self.polling_rate_hz = abs(self.input_settings.get('polling_rate_hz', 120))
        if self.polling_rate_hz == 0: 
            self.polling_rate_hz = 1 
            logger.warning("Polling rate was 0, set to 1 Hz to avoid issues during reload_config.")

        if hasattr(self.jsl_service, 'update_settings'):
            self.jsl_service.update_settings(self.input_settings)
        self.xinput_service.update_settings(self.input_settings)

    def register_input_listener(self, callback):
        """Subscribe a callback(controller_id, input_name, value)."""
        if callback not in self.listeners:
            self.listeners.append(callback)
            logger.info(f"Input listener {callback.__name__} registered.")

    def register_connect_listener(self, callback):
        """Subscribe to controller connect events."""
        if callback not in self.connect_listeners:
            self.connect_listeners.append(callback)
            logger.info(f"Connect listener {callback.__name__} registered.")

    def register_disconnect_listener(self, callback):
        """Subscribe to controller disconnect events."""
        if callback not in self.disconnect_listeners:
            self.disconnect_listeners.append(callback)
            logger.info(f"Disconnect listener {callback.__name__} registered.")

    def register_battery_listener(self, callback: Callable[[str, Tuple[Optional[str], Optional[str]]], None]):
        """Subscribe to battery info updates for connected controllers."""
        if callback not in self.battery_listeners:
            self.battery_listeners.append(callback)
            logger.info(f"Battery listener {callback.__name__} registered.")

    def _notify_input_listeners(self, controller_id, input_name, value):
        """Notify registered listeners of a raw input value change."""
        for listener in self.listeners:
            try:
                listener(controller_id, input_name, value)
            except Exception as e:
                logger.error(f"Error notifying input listener {listener}: {e}", exc_info=True)

    def _notify_connect_listeners(self, controller_id, controller_type_str, device_details):
        """Notify registered listeners of a controller connect event."""
        logger.debug(f"Notifying {len(self.connect_listeners)} connect listeners for {controller_id} ({controller_type_str})")
        for listener in self.connect_listeners:
            try:
                listener(controller_id, controller_type_str, device_details)
            except Exception as e:
                logger.error(f"Error notifying connect listener {listener}: {e}", exc_info=True)

    def _notify_disconnect_listeners(self, controller_id):
        """Notify registered listeners of a controller disconnect event."""
        logger.debug(f"InputService _notify_disconnect_listeners: Notifying {len(self.disconnect_listeners)} disconnect listeners for {controller_id}")
        for callback in self.disconnect_listeners:
            try:
                callback(controller_id)
            except Exception as e:
                logger.error(f"Error in disconnect listener {callback.__name__} for {controller_id}: {e}", exc_info=True)

    def _notify_battery_listeners(self, controller_id: str, battery_info: Tuple[Optional[str], Optional[str]]):
        """Notify registered listeners of a battery info update."""
        logger.debug(f"Notifying {len(self.battery_listeners)} battery listeners for {controller_id}: {battery_info}")
        for listener in self.battery_listeners:
            try:
                listener(controller_id, battery_info)
            except Exception as e:
                logger.error(f"Error notifying battery listener {listener.__name__} for {controller_id}: {e}", exc_info=True)

    def _apply_deadzone_and_curve(self, value, type_str): # Simplified: type_str is 'stick' or 'trigger'
        """Apply deadzone and optional response curve to stick/trigger values.

        Motion values bypass this processing and are returned as-is.
        """
        if type_str == 'motion':
            return value

        deadzone = 0.0
        if type_str == 'stick':
            deadzone = self.input_settings.get('stick_deadzone', 0.1)
        elif type_str == 'trigger':
            deadzone = self.input_settings.get('trigger_deadzone', 0.1)
        
        if abs(value) < deadzone:
            return 0.0
        
        if (1.0 - deadzone) == 0: # Avoid division by zero if deadzone is 1.0
            effective_value = 1.0 if abs(value) >= deadzone else 0.0
        else:
            effective_value = (abs(value) - deadzone) / (1.0 - deadzone)
        
        # Ensure effective_value does not exceed 1.0 due to floating point inaccuracies if value was ~1.0
        effective_value = min(effective_value, 1.0) 
        
        return math.copysign(effective_value, value)

    def _handle_xinput_disconnect_logic(self, user_index, controller_id, reason="disconnected"):
        logger.debug(f"_handle_xinput_disconnect_logic for C{user_index} (ID: {controller_id}), Reason: {reason}")
        self._notify_disconnect_listeners(controller_id)

    def start_polling(self):
        """Start polling of available sub-services (JSL, XInput)."""
        if not self.is_running:
            self.is_running = True
            self.logger.info("InputService: Starting sub-service polling...")
            if self.jsl_service: self.jsl_service.start_polling()
            if self.xinput_service: self.xinput_service.start_polling()
            if not self.jsl_available and not self.xinput_available: self.logger.warning("InputService: No input sub-systems (JSL, XInput) available to poll.")
        else: self.logger.warning("InputService: Polling already requested to be running.")

    def stop_polling(self):
        """Stop polling of sub-services and cleanly shut down threads."""
        if self.is_running:
            self.is_running = False
            self.logger.info("InputService: Stopping sub-service polling...")
            if self.jsl_service: self.jsl_service.stop_polling()
            if self.xinput_service: self.xinput_service.stop_polling()
            self.logger.info("InputService stop sequence complete.")
        else: self.logger.warning("InputService: Polling not currently running.")

    def _trigger_jsl_rescan_internal(self):
        if not self.jsl_service.jsl or self.jsl_service.jsl_subsystem_potentially_unrecoverable: raise RuntimeError("JSL_UNAVAILABLE_OR_UNRECOVERABLE")
        try:
            num_newly_connected = self.jsl_service.jsl.JslScanAndConnectNewDevices()
            MAX_JSL_DEVICES = 16; current_jsl_handles_arr = (ctypes.c_int * MAX_JSL_DEVICES)()
            num_jsl_handles_reported_by_dll = self.jsl_service.jsl.JslGetConnectedDeviceHandles(current_jsl_handles_arr, MAX_JSL_DEVICES)
            current_jsl_handles_set = set(current_jsl_handles_arr[i] for i in range(num_jsl_handles_reported_by_dll))
            disconnected_during_rescan = []
            with self.jsl_service.jsl_devices_lock:
                tracked_handles = list(self.jsl_service.jsl_devices.keys())
                for handle in tracked_handles:
                    if handle not in current_jsl_handles_set and self.jsl_service.jsl_devices[handle].get('connected'):
                        disconnected_id = self.jsl_service._handle_jsl_disconnect_logic(handle, source="internal_gentle_rescan_missing")
                        if disconnected_id: self._notify_disconnect_listeners(disconnected_id)
                        disconnected_during_rescan.append(f"jsl_{handle}")
            if disconnected_during_rescan: logger.info(f"Rescan disconnected: {disconnected_during_rescan}")
            return num_jsl_handles_reported_by_dll
        except Exception as e: self.jsl_service.jsl_subsystem_potentially_unrecoverable = True; raise RuntimeError(f"JSL_RESCAN_FAILED: {e}")

    def jsl_rescan_controllers_action(self):
        if self.jsl_service.jsl_subsystem_potentially_unrecoverable: return {'status': 'error', 'message': "JSL unrecoverable"}
        if not self.jsl_service.jsl: return {'status': 'error', 'message': 'JSL_UNAVAILABLE'}
        try:
            self._trigger_jsl_rescan_internal()
            with self.jsl_service.jsl_devices_lock: final_tracked_count = sum(1 for d in self.jsl_service.jsl_devices.values() if d.get('connected') and d.get('valid_device'))
            if self.socketio: self.socketio.emit('jsl_rescan_status', {'status': 'success', 'count': final_tracked_count })
            return {'status': 'success', 'count': final_tracked_count }
        except RuntimeError as e: return {'status': 'error', 'message': str(e)}
        except Exception as e: return {'status': 'error', 'message': str(e)}
            
    def _disconnect_single_jsl_controller(self, internal_jsl_id_str: str):
        if not self.jsl_service.jsl or not hasattr(self.jsl_service.jsl, 'JslDisconnectDevice'): return False
        try: handle_to_disconnect = int(internal_jsl_id_str.split('_')[-1])
        except: return False
        with self.jsl_service.jsl_devices_lock: device_info = self.jsl_service.jsl_devices.get(handle_to_disconnect);           
        if not device_info or not device_info.get('connected'): return False 
        try:
            success = self.jsl_service.jsl.JslDisconnectDevice(handle_to_disconnect)
            if success:
                disconnected_id = self.jsl_service._handle_jsl_disconnect_logic(handle_to_disconnect, source="single_disconnect_action_success")
                if disconnected_id:
                    self._notify_disconnect_listeners(disconnected_id)
                return True
        except Exception:
            return False
        return False

    def jsl_disconnect_all_controllers_action(self):
        if not self.jsl_service.jsl: return {'status': 'error', 'message': 'JSL_UNAVAILABLE', 'disconnected_ids': []}
        disconnected_ids = []; failed_ids = []
        with self.jsl_service.jsl_devices_lock: handles_to_try_disconnect = [h for h, d in self.jsl_service.jsl_devices.items() if d.get('connected')]
        if not handles_to_try_disconnect: return {'status': 'success', 'message': 'No JSL devices to disconnect.', 'disconnected_ids': []}
        for handle in handles_to_try_disconnect:
            if self._disconnect_single_jsl_controller(f"jsl_{handle}"): disconnected_ids.append(f"jsl_{handle}")
            else: failed_ids.append(f"jsl_{handle}")
        time.sleep(1.0)
        status_emit = {'status': 'success' if not failed_ids else 'partial_fail', 'disconnected_ids': disconnected_ids, 'failed_ids': failed_ids}
        if self.socketio: self.socketio.emit('jsl_disconnect_all_status', status_emit)
        return status_emit

    def get_connected_controllers_status(self):
        statuses = []
        if self.xinput_service and self.xinput_service.xinput_available:
            for i in range(4):
                if self.xinput_service.connected[i]:
                    battery_type, battery_level = self.xinput_service.battery_states[i]
                    statuses.append({
                        "id": f"xinput_{i}",
                        "type": "XInput Controller",
                        "source": "xinput",
                        "battery_type": battery_type,
                        "battery_level": battery_level,
                        "details": {"user_index": i}
                    })
        if self.jsl_service and self.jsl_service.jsl_available:
            with self.jsl_service.jsl_devices_lock:
                for handle, device_data in self.jsl_service.jsl_devices.items():
                    if device_data.get('connected') and device_data.get('valid_device'):
                        statuses.append({
                            "id": device_data.get('id_str'), 
                            "type": device_data.get('type_str'), 
                            "source": "jsl",
                            "details": {"handle": handle, "type_enum": device_data.get('type_enum')}
                            # Battery info for JSL is typically not available directly or consistently
                        })
        return statuses

    def trigger_xinput_rumble(self, user_index: int, repetitions: Optional[int] = None, pulse_duration_s: Optional[float] = None, pause_duration_s: Optional[float] = None, left_intensity: Optional[float] = None, right_intensity: Optional[float] = None) -> bool:
        if self.xinput_service and hasattr(self.xinput_service, 'trigger_xinput_rumble'):
            return self.xinput_service.trigger_xinput_rumble(user_index, repetitions, pulse_duration_s, pause_duration_s, left_intensity, right_intensity)
        self.logger.warning("trigger_xinput_rumble called but XInputService or method not available.")
        return False

    def _on_jsl_connect(self, handle: int, type_enum: int):
        # This method is now called by JSLService._on_jsl_connect_callback_handler
        # with type_enum already determined by JslGetControllerType in JSLService.

        self.logger.info(f"InputService: JSL connect callback processing for handle {handle}, type {type_enum}")

        device_id_str = f"jsl_{handle}"
        type_str = "Unknown JSL Device (Callback Validation Pending)"

        controller_id = device_id_str
        original_type_str = get_jsl_type_string(type_enum) # Get string from original enum
        mapped_type_enum = type_enum # Default to original

        # Directly use the type_enum provided by JSL.
        # The previous logic for mapping specific raw JSL type IDs (e.g., for Pro Controllers) has been removed.
        mapped_type_enum = type_enum
        
        # Update type_str based on the (now direct) mapped_type_enum.
        # The get_jsl_type_string function is still expected to convert this integer ID to a human-readable string.
        type_str = get_jsl_type_string(mapped_type_enum)
        self.logger.info(f"InputService: JSL connect: Using JSL type ID {mapped_type_enum} (directly from JSL), resulting type string: '{type_str}' for handle {handle}.")

        device_details_for_notification = {
            "handle": handle,
            "type_enum": mapped_type_enum, # Use the potentially mapped enum
            "source": "jsl_input_service_on_connect_event" # Clarify event source
        }

        if self.jsl_service:
            # Directly update jsl_service's state. This is not ideal but necessary
            # if jsl_service's own callback handler doesn't fully manage its state before calling this.
            with self.jsl_service.jsl_devices_lock:
                if not hasattr(self.jsl_service, '_ensure_jsl_device_entry'):
                    self.logger.error("JSLService is missing _ensure_jsl_device_entry. Cannot fully process JSL connect in InputService.")
                    # Attempt to notify anyway, but state in JSLService might be incomplete. Device entry might not be properly updated.
                else: # This else is for the 'if not hasattr'
                    self.jsl_service._ensure_jsl_device_entry(handle) # Call it first
                    # Now that entry is ensured, access it
                    if handle in self.jsl_service.jsl_devices: # Check if _ensure_jsl_device_entry actually created/accessed it
                        device_entry = self.jsl_service.jsl_devices[handle]
                        device_entry['type_enum'] = mapped_type_enum # Store the mapped enum
                        device_entry['type_str'] = type_str # Store the string representation of the mapped enum
                        device_entry['connected'] = True
                        device_entry['valid_device'] = True # Assume valid if callback triggered
                        device_entry['error_logged'] = False # Reset error flags
                        device_entry['error_logged_imu'] = False
                        self.logger.info(f"InputService: Updated jsl_service.jsl_devices for jsl_{handle} ({type_str}) INSIDE LOCK.")
                    else:
                        self.logger.error(f"InputService: _ensure_jsl_device_entry was called for handle {handle} but it's still not in jsl_devices dict INSIDE LOCK.")
            
            # This log might be redundant now or misleading if the update inside the lock failed.
            # self.logger.info(f"InputService: Updated jsl_service.jsl_devices for connected jsl_{handle} ({type_str}).") 
            
            self._notify_connect_listeners(controller_id, type_str, device_details_for_notification)

            if self.socketio:
                self.socketio.emit('jsl_device_update', {
                    'status': 'connected',
                    'id': controller_id,
                    'type': type_str,
                    'handle': handle,
                    'type_enum': mapped_type_enum
                })
            else:
                self.logger.debug(f"InputService: SocketIO not available, cannot emit jsl_device_update for jsl_{handle}.")
        else:
            self.logger.error(f"InputService: jsl_service not available, cannot process JSL connect for handle {handle}.")

    def _on_jsl_disconnect(self, handle: int, timed_out: bool, source: str = "jsl_callback_input_service"):
        """
        Called by JSLService's JSL disconnect callback.
        Queues the disconnect event into JSLService's disconnect queue for processing.
        """
        self.logger.info(f"InputService: JSL disconnect callback for handle {handle}, timed_out {timed_out}, source {source}. Queueing in JSLService.")
        if self.jsl_service and hasattr(self.jsl_service, 'jsl_disconnect_queue'):
            self.jsl_service.jsl_disconnect_queue.put({'handle': handle, 'timed_out': timed_out, 'source': source})
        else:
            self.logger.error(f"InputService: jsl_service or its jsl_disconnect_queue not available to queue disconnect for handle {handle}.")