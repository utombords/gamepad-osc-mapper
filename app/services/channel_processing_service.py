"""Channel and variable mapping processing.

This module merges raw controller inputs and applies mapping rules to update
internal OSC channels and variables. It enforces emission cadence, queues OSC
messages via the OSC service, and exposes helpers for layer switching and
configuration-driven behavior.
"""
import logging
import time
import threading
import json
import os

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Load RAW_TO_GENERIC_INPUT_MAP from JSON file
RAW_TO_GENERIC_INPUT_MAP = {}
_definitions_path = os.path.join(os.path.dirname(__file__), '..', 'definitions', 'input_mapping_definitions.json')
try:
    with open(_definitions_path, 'r') as f:
        RAW_TO_GENERIC_INPUT_MAP = json.load(f)
    logger.debug("Loaded input mapping definitions")
except FileNotFoundError:
    logger.error(f"CRITICAL: Input mapping definitions file not found at {_definitions_path}. Mappings will not work.")
except json.JSONDecodeError:
    logger.error(f"CRITICAL: Failed to decode JSON from input mapping definitions file at {_definitions_path}. Mappings will be incorrect.")

BIPOLAR_ANALOG_INPUT_IDS = {"LEFT_STICK_X", "LEFT_STICK_Y", "RIGHT_STICK_X", "RIGHT_STICK_Y",
                            "ACCEL_X", "ACCEL_Y", "ACCEL_Z",
                            "GYRO_X", "GYRO_Y", "GYRO_Z"}
UNIPOLAR_ANALOG_INPUT_IDS = {"LEFT_TRIGGER", "RIGHT_TRIGGER"}

class ChannelProcessingService:
    """Transforms controller inputs into channel/variable updates and OSC output.

    Responsibilities:
    - Maintain merged input state across connected controllers
    - Apply continuous actions (direct, rate, set_value_from_input)
    - Apply discrete actions (toggle, step, reset, variable operations)
    - Enforce per-channel emission cadence and bundle OSC messages
    - Track active layer and re-cache mappings on configuration updates
    """
    def __init__(self, config_service_instance, input_service_instance, socketio_instance, osc_service_instance):
        self.config_service = config_service_instance
        self.input_service = input_service_instance
        self.socketio = socketio_instance
        self.osc_service = osc_service_instance
        logger.info("ChannelProcessing ready")
        
        self.channel_values = {}
        self.channel_values_lock = threading.Lock()
        self.active_layer_id = 'A' 
        self.continuous_actions_lock = threading.Lock()
        self.action_details_for_continuous_processing = {}
        # Activity tracking for cadence while moving
        self.channel_activity_until = {}
        self.activity_emit_window_s = 0.1
        # Per-channel scheduled next emit time for strict cadence during activity
        self.channel_next_emit_time = {}
        
        # Timestamp fields for loop timing
        # (per-input last-handle timestamp removed; not required)

        self.running = True
        self.processing_loop_thread = None
        self.last_processing_loop_time = time.monotonic()
        # Core processing rate; OSC/channel emits are throttled separately
        self.processing_rate_hz = 120.0

        self._initialize_channel_states()
        logger.debug(f"CPS Initial channel_values: {self.channel_values}")

        self.raw_controller_states = {} 
        self.merged_input_states = {}

        self.last_raw_emit_time = 0
        # Frontend raw input updates ~30Hz (UI only)
        self.raw_emit_interval = 1.0 / 30.0  
        # OSC/channel emit target rate (from config osc_settings.max_updates_per_second)
        self.channel_update_emit_interval = 1.0 / 60.0
        self.last_channel_emit_time = {}

        if self.input_service:
            self.input_service.register_input_listener(self.handle_input_update)
            logger.debug("Registered for input/connect/disconnect events")
            self.input_service.register_connect_listener(self.handle_controller_connect)
            self.input_service.register_disconnect_listener(self.handle_controller_disconnect)
        else:
            logger.warning("ChannelProcessingService: InputService instance not provided, cannot register listeners.")

        if self.config_service:
            self.config_service.subscribe_to_config_changes(self._handle_config_updated)
            logger.debug("Subscribed to config changes")
        else:
            logger.warning("ChannelProcessingService: ConfigService instance not provided, cannot subscribe to config changes.")

        # Apply initial cadence from config
        self._refresh_emit_cadence_from_config()
        self._start_processing_loop()
        self._cache_current_layer_mappings()

    def _handle_config_updated(self):
        logger.info("Config updated -> reload CPS state")
        self._initialize_channel_states()
        # Refresh emit cadence based on updated osc_settings
        self._refresh_emit_cadence_from_config()
        self._cache_current_layer_mappings()
        logger.debug("CPS: Finished reloading states after config update.")

    def _refresh_emit_cadence_from_config(self):
        """Refresh the per-channel emit interval from the active OSC settings."""
        try:
            osc_settings = self.config_service.get_osc_settings() if self.config_service else {}
            max_hz = float(osc_settings.get('max_updates_per_second', 60))
            if max_hz <= 0:
                max_hz = 60.0
            if max_hz > 240:
                max_hz = 240.0
            new_interval = 1.0 / max_hz
            if abs(new_interval - self.channel_update_emit_interval) > 1e-6:
                logger.info(f"Cadence: {max_hz:.0f} Hz")
            self.channel_update_emit_interval = new_interval
        except Exception as e:
            logger.warning(f"CPS: Failed to refresh emit cadence from config: {e}. Keeping previous interval {self.channel_update_emit_interval:.6f}s")

    def _clamp_and_snap(self, value: float, min_val: float, max_val: float) -> float:
        """Clamp a value to [min_val, max_val] and snap to endpoints within epsilon."""
        try:
            v = float(value)
        except Exception:
            return min_val
        if v < min_val:
            v = min_val
        elif v > max_val:
            v = max_val
        eps = 1e-9
        if abs(v - min_val) < eps:
            return min_val
        if abs(v - max_val) < eps:
            return max_val
        return v

    def _start_processing_loop(self):
        """Start the background processing loop if not already running."""
        if self.processing_loop_thread is None or not self.processing_loop_thread.is_alive():
            self.running = True
            self.last_processing_loop_time = time.monotonic()
            self.processing_loop_thread = threading.Thread(target=self._continuous_processing_loop, daemon=True)
            self.processing_loop_thread.start()

    def stop_processing_loop(self):
        """Stop the background processing loop and wait briefly for shutdown."""
        logger.info("Stop CPS loop")
        self.running = False
        if self.processing_loop_thread and self.processing_loop_thread.is_alive():
            self.processing_loop_thread.join(timeout=1.5)
            if self.processing_loop_thread.is_alive():
                logger.warning("Continuous processing loop thread did not terminate cleanly.")
            else:
                logger.debug("Continuous processing loop thread joined.")
        self.processing_loop_thread = None
        logger.debug("CPS loop stopped")

    def _cache_current_layer_mappings(self):
        """Cache mappings for the active layer for fast processing in the loop."""
        with self.continuous_actions_lock:
            self.action_details_for_continuous_processing.clear()
            self.discrete_action_mappings_for_current_layer = {}
            self._all_channel_meta_map = {}
            
            config = self.config_service.get_config()
            if not config:
                logger.warning("CPS_CACHE_MAPPINGS: No config available.")
                return

            active_layer_config = config.get('layers', {}).get(self.active_layer_id)
            if not active_layer_config:
                logger.debug(f"CPS_CACHE_MAPPINGS: Active layer '{self.active_layer_id}' not found.")
                return

            active_layer_mappings = active_layer_config.get('input_mappings', {})
            continuous_action_types = {"direct", "rate", "set_value_from_input"}

            for mapped_generic_name, mapping_config in active_layer_mappings.items():
                action = mapping_config.get('action')
                logger.debug(f"CPS_CACHE_MAPPINGS_DETAIL: Layer '{self.active_layer_id}', Input='{mapped_generic_name}', Action='{action}', Config='{mapping_config}'")
                
                if action in continuous_action_types:
                    details = {
                        'action': action,
                        'config': mapping_config, 
                        'target_type': mapping_config.get('target_type') 
                    }
                    target_names = mapping_config.get('target_name')
                    if not isinstance(target_names, list): 
                        target_names = [target_names] if target_names else []

                    if target_names and target_names[0] is not None: 
                        if action == "rate" or \
                           (action == "direct" and details['target_type'] == "osc_channel") or \
                           (action == "set_value_from_input" and details['target_type'] == "osc_channel"):
                            details['channel_meta'] = {}
                            for target_name in target_names:
                                if not target_name: continue
                                channel_data_cfg = config.get('internal_channels', {}).get(target_name, {})
                                min_val = channel_data_cfg.get('min_value', channel_data_cfg.get('range', [0.0, 0.0])[0])
                                max_val = channel_data_cfg.get('max_value', channel_data_cfg.get('range', [0.0, 1.0])[1])
                                osc_addr = channel_data_cfg.get('osc_address')
                                details['channel_meta'][target_name] = {
                                    'min_value': float(min_val),
                                    'max_value': float(max_val),
                                    'osc_address': osc_addr
                                }
                                self._all_channel_meta_map[target_name] = details['channel_meta'][target_name]
                    self.action_details_for_continuous_processing[mapped_generic_name] = details
                else:
                    self.discrete_action_mappings_for_current_layer[mapped_generic_name] = mapping_config

            logger.debug(f"Cache layer '{self.active_layer_id}': cont={len(self.action_details_for_continuous_processing)} disc={len(self.discrete_action_mappings_for_current_layer)}")

    def _continuous_processing_loop(self):
        """Process continuous actions and emit OSC while running.

        Applies continuous actions each tick, performs burst-cadence updates
        for active channels, and sends queued OSC messages in bundles.
        """
        loop_interval = 1.0 / self.processing_rate_hz
        logger.info(f"CPS loop start @ {loop_interval:.4f}s")

        while self.running:
            loop_start_time = time.monotonic()
            loop_delta_time = loop_start_time - self.last_processing_loop_time
            self.last_processing_loop_time = loop_start_time
            
            processed_any_continuous = False
            with self.channel_values_lock:
                with self.continuous_actions_lock:
                    if not self.action_details_for_continuous_processing:
                        processed_any_continuous = False
                    else:
                        processed_any_continuous = True

                    active_actions_this_tick = 0
                    for mapped_generic_name, details in list(self.action_details_for_continuous_processing.items()):
                        action = details['action']
                        mapping_config = details['config']
                        target_type = details.get('target_type')
                        channel_meta_map = details.get('channel_meta', {})
                        current_merged_value = self.merged_input_states.get(mapped_generic_name, 0.0)

                        if action == "rate":
                            target_channel_names_from_map = mapping_config.get('target_name')
                            if not target_channel_names_from_map: 
                                continue
                            
                            actual_target_channels_to_loop = target_channel_names_from_map if isinstance(target_channel_names_from_map, list) else [target_channel_names_from_map]

                            for actual_channel_name in actual_target_channels_to_loop:
                                if not actual_channel_name: 
                                    continue
                                
                                current_channel_val = self.channel_values.get(actual_channel_name, 0.0)
                                channel_meta = channel_meta_map.get(actual_channel_name)
                                if not channel_meta:
                                    logger.warning(f"CPS_LOOP: Missing channel_meta for '{actual_channel_name}' in 'rate' action. Skipping.")
                                    continue

                                rate_multiplier = float(mapping_config.get('params', {}).get('rate_multiplier', 1.0))
                                invert_input = mapping_config.get('params', {}).get('invert', False)
                                input_val_for_rate = current_merged_value
                                if invert_input:
                                    # Invert for rate means flip sign of contribution
                                    input_val_for_rate = -input_val_for_rate
                                
                                change_amount = input_val_for_rate * rate_multiplier * loop_delta_time
                                new_val_before_clamp = current_channel_val + change_amount

                                min_val = channel_meta['min_value']
                                max_val = channel_meta['max_value']
                                new_channel_val_clamped = self._clamp_and_snap(new_val_before_clamp, min_val, max_val)

                                if abs(new_channel_val_clamped - current_channel_val) > 1e-7:
                                    self.channel_values[actual_channel_name] = new_channel_val_clamped
                                    current_time_monotonic = time.monotonic()
                                    last_emit = self.last_channel_emit_time.get(actual_channel_name, 0)
                                    # Always refresh burst-cadence scheduling on value change
                                    self.channel_activity_until[actual_channel_name] = current_time_monotonic + self.activity_emit_window_s
                                    self.channel_next_emit_time[actual_channel_name] = current_time_monotonic + self.channel_update_emit_interval
                                    if (current_time_monotonic - last_emit) >= self.channel_update_emit_interval:
                                        if self.socketio:
                                            self.socketio.emit('channel_value_update', {'name': actual_channel_name, 'value': new_channel_val_clamped})
                                        if self.osc_service:
                                            self.osc_service.handle_value_update('channel', actual_channel_name, new_channel_val_clamped)
                                        self.last_channel_emit_time[actual_channel_name] = current_time_monotonic
                                active_actions_this_tick += 1
                        
                        elif action == "direct":
                            target_name_from_map = mapping_config.get('target_name')
                            if not target_name_from_map: 
                                continue
                            
                            actual_target_name = target_name_from_map[0] if isinstance(target_name_from_map, list) else target_name_from_map
                            if not actual_target_name: 
                                continue

                            if target_type == "osc_channel":
                                channel_meta = channel_meta_map.get(actual_target_name)
                                if not channel_meta:
                                    logger.warning(f"CPS_LOOP: Missing channel_meta for '{actual_target_name}' in 'direct' OSC action. Skipping.")
                                    continue

                                input_val_for_direct = current_merged_value
                                is_bipolar = mapped_generic_name in BIPOLAR_ANALOG_INPUT_IDS
                                is_unipolar_trigger = mapped_generic_name in UNIPOLAR_ANALOG_INPUT_IDS
                                
                                if is_bipolar:
                                    scaled_input_value = (input_val_for_direct + 1.0) / 2.0
                                elif is_unipolar_trigger:
                                    scaled_input_value = input_val_for_direct
                                else:
                                    scaled_input_value = float(input_val_for_direct)

                                invert_mapping = mapping_config.get('params', {}).get('invert', False)
                                if invert_mapping:
                                    scaled_input_value = 1.0 - scaled_input_value
                                
                                min_val = channel_meta['min_value']
                                max_val = channel_meta['max_value']
                                range_val = max_val - min_val
                                new_direct_val = (scaled_input_value * range_val) + min_val
                                clamped_scaled_value = self._clamp_and_snap(new_direct_val, min_val, max_val)

                                if self.channel_values.get(actual_target_name) != clamped_scaled_value:
                                    self.channel_values[actual_target_name] = clamped_scaled_value
                                    current_time_monotonic = time.monotonic()
                                    last_emit = self.last_channel_emit_time.get(actual_target_name, 0)
                                    # For analog inputs, always refresh burst-cadence scheduling on change
                                    if is_bipolar or is_unipolar_trigger:
                                        self.channel_activity_until[actual_target_name] = current_time_monotonic + self.activity_emit_window_s
                                        self.channel_next_emit_time[actual_target_name] = current_time_monotonic + self.channel_update_emit_interval
                                    if (current_time_monotonic - last_emit) >= self.channel_update_emit_interval:
                                        if self.socketio:
                                            self.socketio.emit('channel_value_update', {'name': actual_target_name, 'value': clamped_scaled_value})
                                        if self.osc_service:
                                            self.osc_service.handle_value_update('channel', actual_target_name, clamped_scaled_value)
                                        self.last_channel_emit_time[actual_target_name] = current_time_monotonic
                                active_actions_this_tick += 1

                        elif action == "set_value_from_input":
                            if target_type == "internal_variable":
                                target_variable_name = mapping_config.get('target_name')
                                if not target_variable_name: 
                                    continue
                                value_to_set = current_merged_value
                                if mapping_config.get('params', {}).get('invert_input_value', False):
                                    value_to_set = 1.0 - value_to_set if 0 <= value_to_set <= 1 else value_to_set
                                
                                current_var_val = self.config_service.get_internal_variable_value(target_variable_name)
                                if current_var_val != value_to_set:
                                    self.config_service.set_internal_variable_value(target_variable_name, value_to_set)
                                active_actions_this_tick +=1
                            elif target_type == "osc_channel": 
                                target_channel_names_from_map = mapping_config.get('target_name')
                                if not target_channel_names_from_map: 
                                    continue
                                
                                actual_target_channels_to_loop = target_channel_names_from_map if isinstance(target_channel_names_from_map, list) else [target_channel_names_from_map]
                                value_to_set = float(mapping_config.get('params', {}).get('value_to_set', current_merged_value))

                                for actual_channel_name in actual_target_channels_to_loop:
                                    if not actual_channel_name: 
                                        continue
                                    channel_meta = channel_meta_map.get(actual_channel_name)
                                    if not channel_meta: 
                                        continue

                                    min_val = channel_meta['min_value']
                                    max_val = channel_meta['max_value']
                                    clamped_value_to_set = self._clamp_and_snap(value_to_set, min_val, max_val)

                                    if self.channel_values.get(actual_channel_name) != clamped_value_to_set:
                                        self.channel_values[actual_channel_name] = clamped_value_to_set
                                        current_time_monotonic = time.monotonic()
                                        last_emit = self.last_channel_emit_time.get(actual_channel_name, 0)
                                        # Always refresh burst-cadence scheduling on value change
                                        self.channel_activity_until[actual_channel_name] = current_time_monotonic + self.activity_emit_window_s
                                        self.channel_next_emit_time[actual_channel_name] = current_time_monotonic + self.channel_update_emit_interval
                                        if (current_time_monotonic - last_emit) >= self.channel_update_emit_interval:
                                            if self.socketio:
                                                self.socketio.emit('channel_value_update', {'name': actual_channel_name, 'value': clamped_value_to_set})
                                            if self.osc_service:
                                                self.osc_service.handle_value_update('channel', actual_channel_name, clamped_value_to_set)
                                            self.last_channel_emit_time[actual_channel_name] = current_time_monotonic
                                        active_actions_this_tick += 1
                    # Only send when values actually change

            # Burst cadence while active: emit at interval for channels marked active
            now = time.monotonic()
            if processed_any_continuous:
                for ch_name, until_ts in list(self.channel_activity_until.items()):
                    if until_ts <= now:
                        continue
                    next_due = self.channel_next_emit_time.get(ch_name, 0.0)
                    if now >= next_due:
                        meta = self._all_channel_meta_map.get(ch_name)
                        if not meta:
                            continue
                        current_val = self.channel_values.get(ch_name)
                        if current_val is None:
                            continue
                        if self.socketio:
                            self.socketio.emit('channel_value_update', {'name': ch_name, 'value': current_val})
                        if meta.get('osc_address') and self.osc_service:
                            self.osc_service.handle_value_update('channel', ch_name, current_val)
                        self.last_channel_emit_time[ch_name] = now
                        # schedule next due time aligned to cadence
                        self.channel_next_emit_time[ch_name] = next_due + self.channel_update_emit_interval

            if self.osc_service:
                self.osc_service.send_bundled_messages()

            # Coarse sleep to next loop
            elapsed_in_loop = time.monotonic() - loop_start_time
            sleep_duration = loop_interval - elapsed_in_loop
            if sleep_duration > 0:
                time.sleep(sleep_duration)
        
        logger.debug("CPS loop exited")

    def _get_generic_input_name(self, raw_input_name):
        """Map a backend-specific input name to a generic ID using definitions."""
        return RAW_TO_GENERIC_INPUT_MAP.get(raw_input_name, raw_input_name)

    def _update_merged_states(self):
        """Merge raw states from all controllers into a single normalized state map."""
        all_generic_names = set(RAW_TO_GENERIC_INPUT_MAP.values())
        imu_axes = {"ACCEL_X", "ACCEL_Y", "ACCEL_Z", "GYRO_X", "GYRO_Y", "GYRO_Z"}
        all_generic_names.update(imu_axes)
        self.merged_input_states = {name: 0.0 for name in all_generic_names}
        
        analog_inputs_to_initialize = [
            "LEFT_STICK_X", "LEFT_STICK_Y", "RIGHT_STICK_X", "RIGHT_STICK_Y", 
            "LEFT_TRIGGER", "RIGHT_TRIGGER",
            "ACCEL_X", "ACCEL_Y", "ACCEL_Z", "GYRO_X", "GYRO_Y", "GYRO_Z"
        ]
        for analog_input in analog_inputs_to_initialize:
            self.merged_input_states[analog_input] = 0.0

        active_controllers = [cid for cid, states in self.raw_controller_states.items() if states]
        if not active_controllers:
            return

        temp_merged_analog = {
            "LEFT_STICK_X": 0.0, "LEFT_STICK_Y": 0.0,
            "RIGHT_STICK_X": 0.0, "RIGHT_STICK_Y": 0.0,
            "LEFT_TRIGGER": 0.0, "RIGHT_TRIGGER": 0.0,
            "ACCEL_X": 0.0, "ACCEL_Y": 0.0, "ACCEL_Z": 0.0,
            "GYRO_X": 0.0, "GYRO_Y": 0.0, "GYRO_Z": 0.0
        }

        for controller_id, raw_inputs in self.raw_controller_states.items():
            if not raw_inputs: continue
            for raw_name, value in raw_inputs.items():
                generic_name = self._get_generic_input_name(raw_name)
                float_value = float(value)

                if generic_name in ["LEFT_STICK_X", "RIGHT_STICK_X", "ACCEL_X", "ACCEL_Y", "ACCEL_Z", "GYRO_X", "GYRO_Y", "GYRO_Z"]:
                    temp_merged_analog[generic_name] += float_value
                elif generic_name in ["LEFT_STICK_Y", "RIGHT_STICK_Y"]:
                    temp_merged_analog[generic_name] += float_value
                elif generic_name in ["LEFT_TRIGGER", "RIGHT_TRIGGER"]:
                    temp_merged_analog[generic_name] = max(temp_merged_analog.get(generic_name, 0.0), float_value)
                else:
                    # Digital/buttons: OR across controllers (any press keeps it 1.0)
                    if float_value >= 1.0:
                        self.merged_input_states[generic_name] = 1.0

        for stick_axis in ["LEFT_STICK_X", "LEFT_STICK_Y", "RIGHT_STICK_X", "RIGHT_STICK_Y", "ACCEL_X", "ACCEL_Y", "ACCEL_Z", "GYRO_X", "GYRO_Y", "GYRO_Z"]:
            if stick_axis in temp_merged_analog:
                 self.merged_input_states[stick_axis] = max(-1.0, min(1.0, temp_merged_analog[stick_axis]))
        
        for trigger_axis in ["LEFT_TRIGGER", "RIGHT_TRIGGER"]:
            if trigger_axis in temp_merged_analog:
                self.merged_input_states[trigger_axis] = max(0.0, min(1.0, temp_merged_analog[trigger_axis]))

    def handle_controller_connect(self, controller_id, controller_type_str, device_details):
        """Handle controller connect event from an input service."""
        logger.info(f"Controller connected: {controller_id} ({controller_type_str})")
        if controller_id not in self.raw_controller_states:
            self.raw_controller_states[controller_id] = {}

    def handle_controller_disconnect(self, controller_id):
        """Handle controller disconnect event and refresh merged state/UI."""
        logger.info(f"Controller disconnected: {controller_id}")
        if controller_id in self.raw_controller_states:
            self.raw_controller_states.pop(controller_id, None)
        
        logger.debug(f"CPS: Raw states after disconnect of {controller_id}: {self.raw_controller_states}")
        self._update_merged_states()
        if self.socketio:
            self.socketio.emit('raw_inputs_update', self.raw_controller_states)
            logger.debug(f"CPS: Emitted raw_inputs_update after disconnect of {controller_id}")

    def handle_input_update(self, controller_id, input_name, value):
        """Receive a raw input update and process discrete actions immediately.

        Continuous actions are handled in the background loop; this method
        only updates merged state and applies discrete mappings.
        """
        # Per-event delta tracking not needed; loop uses its own precise timing
        current_time = time.monotonic()

        generic_input_name = self._get_generic_input_name(input_name)
        if not generic_input_name:
            logger.debug(f"CPS_HANDLE_INPUT_UPDATE: No generic mapping for raw input '{input_name}'.")
            return

        with self.continuous_actions_lock:
            if controller_id not in self.raw_controller_states:
                self.raw_controller_states[controller_id] = {}
            self.raw_controller_states[controller_id][generic_input_name] = value
            self._update_merged_states()

            if self.socketio and (current_time - self.last_raw_emit_time > self.raw_emit_interval):
                self.socketio.emit('raw_inputs_update', self.raw_controller_states)
                self.last_raw_emit_time = current_time
        
        with self.continuous_actions_lock:
            mapping_config = self.discrete_action_mappings_for_current_layer.get(generic_input_name)

        if not mapping_config:
            return

        logger.debug(f"CPS_HANDLE_DISCRETE: Layer '{self.active_layer_id}', Input='{generic_input_name}', Value={value}, Action='{mapping_config.get('action')}', Config='{mapping_config}'")

        action = mapping_config.get('action')
        params = mapping_config.get('params', {})
        target_type = mapping_config.get('target_type')
        target_name_or_names = mapping_config.get('target_name')

        actual_target_names = []
        if isinstance(target_name_or_names, list):
            actual_target_names = target_name_or_names
        elif target_name_or_names:
            actual_target_names = [target_name_or_names]
        
        current_time = time.monotonic()

        if target_type == "osc_channel":
            if not actual_target_names:
                logger.warning(f"CPS_HANDLE_DISCRETE: No target OSC channel names for action '{action}' on input '{generic_input_name}'.")
                return

            for actual_channel_name in actual_target_names:
                if not actual_channel_name: continue

                channel_config = self.config_service.get_config().get('internal_channels', {}).get(actual_channel_name, {})
                min_val = float(channel_config.get('min_value', channel_config.get('range', [0.0, 0.0])[0]))
                max_val = float(channel_config.get('max_value', channel_config.get('range', [0.0, 1.0])[1]))
                # Use 'default' field; fall back to min if absent
                default_val = float(channel_config.get('default', min_val))
                osc_address = channel_config.get('osc_address')
                
                current_channel_value = self.channel_values.get(actual_channel_name, default_val)
                value_to_emit_if_changed = None

                if action == "toggle":
                    if value >= self.input_service.button_press_threshold:
                        new_val = max_val if abs(current_channel_value - min_val) < 1e-6 else min_val
                        if current_channel_value != new_val:
                            self.channel_values[actual_channel_name] = new_val
                            value_to_emit_if_changed = new_val

                elif action == "step_by_multiplier_on_trigger":
                    if value >= self.input_service.button_press_threshold:
                        multiplier = float(params.get('multiplier', 1.0))
                        current_val_for_step = self.channel_values.get(actual_channel_name, default_val)
                        new_val = current_val_for_step + multiplier
                        new_val_clamped = max(min_val, min(max_val, new_val))
                        if current_channel_value != new_val_clamped:
                            self.channel_values[actual_channel_name] = new_val_clamped
                            value_to_emit_if_changed = new_val_clamped

                elif action == "reset_channel_on_trigger":
                    if value >= self.input_service.button_press_threshold:
                        if current_channel_value != default_val:
                            self.channel_values[actual_channel_name] = default_val
                            value_to_emit_if_changed = default_val
                
                if value_to_emit_if_changed is not None:
                    logger.debug(f"CPS_HANDLE_DISCRETE: Channel '{actual_channel_name}' changed to {value_to_emit_if_changed} by action '{action}'.")
                    current_time_monotonic = time.monotonic() # Use separate monotonic for emit throttle
                    last_emit = self.last_channel_emit_time.get(actual_channel_name, 0)
                    if (current_time_monotonic - last_emit) > self.channel_update_emit_interval:
                        if self.socketio:
                            self.socketio.emit('channel_value_update', {'name': actual_channel_name, 'value': value_to_emit_if_changed})
                            self.last_channel_emit_time[actual_channel_name] = current_time_monotonic
                    if osc_address and self.osc_service:
                        self.osc_service.handle_value_update('channel', actual_channel_name, value_to_emit_if_changed)

        elif target_type == "internal_variable":
            target_variable_name = mapping_config.get('target_name')
            if not target_variable_name:
                return
            current_val = self.config_service.get_internal_variable_value(target_variable_name)
            if current_val is None:
                return
            new_val = current_val
            # Handle actions for variables
            if action == 'step_by_multiplier_on_trigger':
                if value >= self.input_service.button_press_threshold:
                    step = float(params.get('multiplier', 1.0))
                    new_val = current_val + step
            elif action == 'increment':
                if value >= self.input_service.button_press_threshold:
                    step = float(params.get('step', 1.0))
                    new_val = current_val + step
            elif action == 'decrement':
                if value >= self.input_service.button_press_threshold:
                    step = float(params.get('step', 1.0))
                    new_val = current_val - step
            elif action == 'set_value_from_input':
                # Map input directly to variable (optionally invert)
                new_val = value
                if params.get('invert_input_value', False):
                    new_val = 1.0 - new_val if 0.0 <= new_val <= 1.0 else -new_val
            elif action == 'set_variable':
                if value >= self.input_service.button_press_threshold:
                    new_val = float(params.get('target_value', current_val))
            elif action == 'toggle_variable':
                if value >= self.input_service.button_press_threshold:
                    new_val = 0.0 if current_val else 1.0

            if new_val != current_val:
                if self.config_service.set_internal_variable_value(target_variable_name, new_val):
                    # Briefly suppress sending of channels whose addresses depend on variables
                    if self.osc_service and hasattr(self.osc_service, 'suppress_variable_expanded_channels'):
                        self.osc_service.suppress_variable_expanded_channels(0.1)
                    # Read back the effective (clamped) value from config
                    effective_val = self.config_service.get_internal_variable_value(target_variable_name)
                    if self.socketio:
                        self.socketio.emit('variable_value_updated', {'name': target_variable_name, 'value': effective_val})
                    # If variable configured to send OSC on change, queue it
                    var_cfg = self.config_service.get_config().get('internal_variables', {}).get(target_variable_name, {})
                    if var_cfg.get('on_change_osc', {}).get('enabled', False):
                        address = var_cfg['on_change_osc'].get('address')
                        if address and self.osc_service:
                            value_type = var_cfg['on_change_osc'].get('value_type', 'float')
                            content = var_cfg['on_change_osc'].get('value_content', 'value')
                            # Expand placeholders in address/content using effective value
                            address = self._expand_placeholders(address, target_variable_name, effective_val)
                            send_value = self._expand_osc_value(content, value_type, target_variable_name, effective_val, var_cfg)
                            self.osc_service.send_custom_osc_message(address, send_value, value_type)

        if action == "change_layer" or action == "activate_layer":
            if value > 0.5: 
                new_layer_id = None
                if action == "change_layer":
                    new_layer_id = params.get('target_layer_id')
                elif action == "activate_layer":
                    new_layer_id = mapping_config.get('target_name')

                logger.debug(f"CPS_LAYER_SWITCH: Action='{action}'. Attempting to change to layer '{new_layer_id}' from '{self.active_layer_id}'. Input val: {value}")
                if new_layer_id:
                    logger.debug(f"CPS_LAYER_SWITCH: new_layer_id '{new_layer_id}' is valid. Calling set_active_layer.")
                    self.set_active_layer(new_layer_id, mapping_config, value)
                    logger.debug(f"CPS_LAYER_SWITCH: set_active_layer was called. Current active layer now: {self.active_layer_id}")
                else:
                    if action == "change_layer":
                        logger.warning(f"CPS_LAYER_SWITCH: No target_layer_id found in params for 'change_layer': {params}")
                    elif action == "activate_layer":
                        logger.warning(f"CPS_LAYER_SWITCH: No target_name found in mapping_config for 'activate_layer': {mapping_config}")
            else:
                logger.debug(f"CPS_LAYER_SWITCH: Input value {value} not > 0.5, no layer change triggered for action '{action}'.")
        
        # 'momentary_layer' action not implemented

    def _expand_placeholders(self, address: str, variable_name: str, value) -> str:
        """Expand {var} and {value} tokens in an OSC address or content string."""
        try:
            # Support only {var} and {value} tokens
            return address.replace('{var}', str(variable_name)).replace('{value}', str(value))
        except Exception:
            return address

    def _expand_osc_value(self, value_content: str, value_type: str, variable_name: str, value, var_cfg: dict):
        """Resolve a variable's OSC value content into a concrete value of the declared type."""
        # Supports 'value', 'normalized_value', '{var}', '{value}', or fixed strings/numbers/bools
        if not isinstance(value_content, str):
            return value
        token = value_content.strip().lower()
        if token == 'value':
            return value
        if token == 'normalized_value':
            min_v = var_cfg.get('min_value')
            max_v = var_cfg.get('max_value')
            if min_v is not None and max_v is not None:
                try:
                    min_f = float(min_v); max_f = float(max_v)
                    if max_f > min_f:
                        return max(0.0, min(1.0, (float(value) - min_f) / (max_f - min_f)))
                except Exception:
                    pass
            return value
        # Allow placeholders in fixed content using {var} and {value}
        expanded = value_content.replace('{var}', str(variable_name)).replace('{value}', str(value))
        # Coerce to the declared type if possible
        try:
            if value_type == 'int':
                return int(float(expanded))
            if value_type == 'float':
                return float(expanded)
            if value_type == 'bool':
                return str(expanded).lower() in ('1', 'true', 'on', 'yes')
            return str(expanded)
        except Exception:
            return expanded

    def set_active_layer(self, new_layer_id, triggering_mapping_config=None, input_value=None):
        """Activate a new mapping layer and optionally send an OSC notification."""
        logger.debug(f"SET_ACTIVE_LAYER: Called with NewLayerID='{new_layer_id}', CurrentActiveLayer='{self.active_layer_id}', TriggerInputVal='{input_value}'")
        if not new_layer_id or not isinstance(new_layer_id, str) or not new_layer_id.strip():
            logger.warning(f"SET_ACTIVE_LAYER: Invalid new_layer_id received: '{new_layer_id}'. Aborting layer change.")
            return

        if self.active_layer_id == new_layer_id:
            logger.debug(f"ChannelProcessingService: Layer {new_layer_id} is already active.")
            return

        previous_layer_id = self.active_layer_id
        self.active_layer_id = new_layer_id
        logger.info(f"ChannelProcessingService: Active layer changed from {previous_layer_id} to {new_layer_id}")
        self._cache_current_layer_mappings()

        if triggering_mapping_config and self.osc_service:
            on_change_osc_config = triggering_mapping_config.get('params', {}).get('on_change_osc')
            if on_change_osc_config and on_change_osc_config.get('enabled') and on_change_osc_config.get('address'):
                address = on_change_osc_config['address']
                value_str = on_change_osc_config.get('value', '1')
                value_type = on_change_osc_config.get('value_type', 'float')
                
                actual_value = None
                try:
                    if value_type == 'float':
                        actual_value = float(value_str)
                    elif value_type == 'integer':
                        actual_value = int(value_str)
                    elif value_type == 'boolean':
                        actual_value = 1 if value_str.lower() in ['1', 'true', 'on', 'yes'] else 0
                    elif value_type == 'string':
                        actual_value = value_str
                    else:
                        logger.warning(f"Unsupported OSC value_type '{value_type}' for layer change OSC.")
                        return
                except ValueError as e:
                    logger.error(f"Could not convert OSC value '{value_str}' to type '{value_type}': {e}")
                    return

                logger.info(f"Sending OSC message on layer change: Addr: {address}, Val: {actual_value} (Type: {value_type})")
                self.osc_service.send_custom_osc_message(address, actual_value)
            else:
                logger.debug("No on_change_osc configured or enabled for this layer switch.")

    

    def _initialize_channel_states(self):
        """Initialize or preserve channel values according to configuration.

        Preserves existing values when possible, clamping to new ranges on
        configuration reloads; otherwise uses a channel default or its minimum.
        """
        logger.debug("Initializing channel states from configuration (preserve existing where possible)...")
        config = self.config_service.get_config()
        if not config or 'internal_channels' not in config:
            logger.warning("CPS: No internal_channels found in config during state initialization.")
            return

        internal_channels_config = config.get('internal_channels', {})
        new_channel_values = {}
        for channel_name, ch_config in internal_channels_config.items():
            if not isinstance(ch_config, dict):
                logger.warning(f"CPS: Configuration for channel '{channel_name}' is not a dict. Skipping.")
                continue
            try:
                min_val = float(ch_config.get('min_value', ch_config.get('range', [0.0, 0.0])[0]))
                max_val = float(ch_config.get('max_value', ch_config.get('range', [0.0, 1.0])[1]))
            except Exception:
                min_val, max_val = 0.0, 1.0
            try:
                default_value = float(ch_config.get('default', min_val))
            except Exception:
                default_value = min_val

            if channel_name in self.channel_values:
                try:
                    cur = float(self.channel_values[channel_name])
                except Exception:
                    cur = default_value
                new_channel_values[channel_name] = self._clamp_and_snap(cur, min_val, max_val)
            else:
                new_channel_values[channel_name] = default_value

        self.channel_values = new_channel_values
        logger.debug("Channel states initialized")


