"""Configuration management service.

Handles loading, saving, and updating persistent configuration files. Exposes
helpers for OSC settings, input settings, variables, channels, and mapping
CRUD operations. Provides a simple pub/sub mechanism to notify subscribers of
config changes.
"""
import logging
from threading import Lock
from typing import Dict, Any

logger = logging.getLogger(__name__)

import json
import os
import copy
import sys

def _get_writable_config_dir() -> str:
    """Return a directory path suitable for writing configs at runtime.

    Frozen builds write next to the executable. Development uses repo /configs.
    The environment variable GAMEPAD_OSC_CONFIG_DIR overrides both.
    """
    env_override = os.environ.get('GAMEPAD_OSC_CONFIG_DIR')
    if env_override and env_override.strip():
        return os.path.abspath(env_override)

    # If running as a frozen EXE, put configs next to the executable
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        return os.path.join(exe_dir, 'configs')

    # Dev mode: use repo's /configs directory
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'configs'))

# Default config file (read-only resource) – try bundled location if present
try:
    _RESOURCE_BASE = getattr(sys, '_MEIPASS', os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
except Exception:
    _RESOURCE_BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
DEFAULT_CONFIG_FILE = os.path.join(_RESOURCE_BASE, 'configs', 'default_config.json')

DEFAULT_INTERNAL_CHANNELS = {
}

DEFAULT_VARIABLES = {
}

class ConfigService:
    _instance = None
    _lock = Lock()

    def __init__(self):
        if hasattr(self, '_initialized') and self._initialized:
            return # Already initialized
        
        self._initialized = False # Set early to prevent re-entry during init
        self.logger = logger
        self.config_data: Dict[str, Any] = {}
        self.default_config_data: Dict[str, Any] = {}
        self._config_change_subscribers: list = [] # ADDED: Initialize subscriber list
        # Writable config directory (persistent across runs)
        self.config_dir = _get_writable_config_dir()
        self.active_config_path = os.path.join(self.config_dir, 'active_config.json')
        self.default_config_path = os.path.join(self.config_dir, 'default_config.json')
        
        self.logger.info(f"ConfigService Initialized (from services module)")

        if not os.path.exists(self.config_dir):
            try:
                os.makedirs(self.config_dir)
                logger.info(f"Created configuration directory: {self.config_dir}")
            except OSError as e:
                logger.error(f"Failed to create configuration directory {self.config_dir}: {e}")
                # Handle error appropriately, maybe raise an exception or use in-memory only

        self.active_config = self._load_initial_config()
        if not self.active_config: # Fallback if active_config.json was invalid or empty
            logger.warning("Initial config loading failed or was empty, loading defaults.")
            self.active_config = self._get_default_config()
            self.save_active_config() # Save the defaults as active if nothing was there

    def _load_config_from_file(self, file_path):
        """Load JSON config from file, returning a dict or None on error."""
        if not os.path.exists(file_path):
            logger.info(f"Config file not found: {file_path}")
            return None
        try:
            with open(file_path, 'r') as f:
                config_data = json.load(f)
                logger.info(f"Successfully loaded configuration from {file_path}")
                return config_data
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding JSON from {file_path}: {e}")
            return None # Or handle corrupted file, e.g., by loading defaults
        except Exception as e:
            logger.error(f"Error reading config file {file_path}: {e}")
            return None

    def _get_default_config(self):
        """Return the default configuration, preferring a bundled preset if present."""
        logger.info("Loading default configuration structure.")
        # First, try to load from default_config.json if it exists
        default_preset = self._load_config_from_file(DEFAULT_CONFIG_FILE)
        if default_preset:
            logger.info(f"Using default configuration from {DEFAULT_CONFIG_FILE}")
            return default_preset
        
        # If default_config.json doesn't exist or fails to load, use hardcoded defaults
        logger.info(f"{DEFAULT_CONFIG_FILE} not found or invalid, using hardcoded default config.")
        return {
            "osc_settings": { "ip": "127.0.0.1", "port": 9000, "max_updates_per_second": 60 },
            "web_settings": { "host": "127.0.0.1", "port": 5000 },
            "input_settings": {
                "stick_deadzone": 0.1,
                "trigger_deadzone": 0.05,
                "stick_curve": "linear",
                "polling_rate_hz": 120,
                "battery_check_interval_seconds": 5,
                "jsl_rescan_interval_s": 30.0,
                "jsl_rescan_polling": True
            },
            "internal_channels": DEFAULT_INTERNAL_CHANNELS,
            "internal_variables": DEFAULT_VARIABLES,
            "layers": {
                'A': { "name": "Layer A", "input_mappings": {} },
                'B': { "name": "Layer B", "input_mappings": {} },
                'C': { "name": "Layer C", "input_mappings": {} },
                'D': { "name": "Layer D", "input_mappings": {} }
            },
            "layer_keybinds": { 'A': None, 'B': None, 'C': None, 'D': None },
            "layer_change_osc_actions": {
                'A': {"enabled": False, "address": "/layer/a/active", "value_type": "int", "value_str": "1"}
            }
        }

    def _load_initial_config(self):
        """Load the active configuration from disk if available, else None."""
        logger.info(f"Attempting to load active configuration from {self.active_config_path}...")
        config = self._load_config_from_file(self.active_config_path)
        if config:
            return config
        logger.info(f"{self.active_config_path} not found or invalid. Will try defaults.")
        return None

    def save_config_to_file(self, config_data, file_path):
        """Persist the provided config dict to the specified path as JSON."""
        try:
            if 'input_settings' in config_data:
                logger.info(f"ConfigService: About to save input_settings: {config_data['input_settings']}")
            else:
                logger.info("ConfigService: input_settings key not found in config_data before saving.")
            
            with open(file_path, 'w') as f:
                json.dump(config_data, f, indent=4)
            logger.info(f"Configuration successfully saved to {file_path}")
            return True
        except Exception as e:
            logger.error(f"Error saving configuration to {file_path}: {e}")
            return False

    def save_active_config(self):
        """Save the active config and notify subscribers on success."""
        logger.info(f"Saving active configuration to {self.active_config_path}...")
        success = self.save_config_to_file(self.active_config, self.active_config_path)
        if success:
            self._notify_config_change_subscribers()
        return success

    def get_config(self):
        """Return a deep copy of the active configuration."""
        return copy.deepcopy(self.active_config)

    def update_config_section(self, section_key, section_data):
        """Replace a top-level config section (e.g., 'osc_settings') and save."""
        if section_key in self.active_config:
            self.active_config[section_key] = section_data
            logger.info(f"Updated config section: {section_key}")
            if self.save_active_config(): # This now also handles notification
                logger.debug(f"Config section {section_key} updated and subscribers notified.")
            return True
        else:
            logger.warning(f"Attempted to update non-existent config section: {section_key}")
            return False

    def get_osc_settings(self):
        return copy.deepcopy(self.active_config.get("osc_settings", {}))

    def get_web_settings(self):
        """Return the web server settings from the active configuration."""
        return copy.deepcopy(self.active_config.get("web_settings", {}))

    def get_input_settings(self):
        """Return the input processing settings from the active configuration."""
        return copy.deepcopy(self.active_config.get("input_settings", {}))

    def add_internal_channel(self, channel_properties):
        """Add a new internal channel with the provided properties."""
        channel_name = channel_properties.get('name')
        if not channel_name:
            return False, "Channel properties must include a 'name'.", self.active_config

        if 'internal_channels' not in self.active_config:
            self.active_config['internal_channels'] = {}
        
        if channel_name in self.active_config['internal_channels']:
            return False, f"Channel '{channel_name}' already exists.", self.active_config

        # Basic validation/sanitization could be added here if needed
        self.active_config['internal_channels'][channel_name] = channel_properties
        self.save_active_config()
        logger.info(f"Added internal channel: {channel_name}")
        return True, f"Channel '{channel_name}' added successfully.", self.active_config

    def update_internal_channel(self, channel_name, properties_to_update):
        """Update properties of an existing internal channel by name."""
        if 'internal_channels' not in self.active_config or \
           channel_name not in self.active_config['internal_channels']:
            return False, f"Channel '{channel_name}' not found for update.", self.active_config

        # Ensure name is not changed via this method if it's part of properties_to_update
        if 'name' in properties_to_update and properties_to_update['name'] != channel_name:
            logger.warning(f"Attempt to change channel name from '{channel_name}' to '{properties_to_update['name']}' via update_internal_channel is not allowed.")
            # Decide on behavior: reject, or ignore name change. For now, ignore.
            del properties_to_update['name']

        self.active_config['internal_channels'][channel_name].update(properties_to_update)
        self.save_active_config()
        logger.info(f"Updated internal channel: {channel_name} with {properties_to_update}")
        return True, f"Channel '{channel_name}' updated successfully.", self.active_config

    def delete_internal_channel(self, channel_name):
        """Delete an internal channel and clear dependent mapping references."""
        if 'internal_channels' not in self.active_config or \
           channel_name not in self.active_config['internal_channels']:
            return False, f"Channel '{channel_name}' not found for deletion.", self.active_config

        del self.active_config['internal_channels'][channel_name]
        logger.info(f"Deleted internal channel: {channel_name}")

        # Remove references from layer input mappings
        layers = self.active_config.get('layers', {})
        for layer_id, layer_data in layers.items():
            if 'input_mappings' in layer_data:
                mappings_to_delete = []
                for input_name, mapping_details in layer_data['input_mappings'].items():
                    target = mapping_details.get('target')
                    modified = False
                    if isinstance(target, str) and target == channel_name:
                        # Option 2: Clear the target (making it an unmapped input)
                        mapping_details['target'] = None # Or an empty string/specific marker
                        mapping_details['action'] = None # Clear action as well
                        # Add more fields to clear as necessary based on mapping structure
                        logger.info(f"Cleared target for input '{input_name}' in layer '{layer_id}' due to channel '{channel_name}' deletion.")
                        modified = True
                    elif isinstance(target, list) and channel_name in target:
                        target.remove(channel_name)
                        logger.info(f"Removed '{channel_name}' from target list for input '{input_name}' in layer '{layer_id}'. New target: {target}")
                        if not target: # If list becomes empty
                            mapping_details['target'] = None
                            mapping_details['action'] = None
                        modified = True
                    
                # Lines related to "Option 1" previously here are now removed.

        self.save_active_config()
        return True, f"Channel '{channel_name}' deleted successfully and references cleared.", self.active_config

    def add_internal_variable(self, variable_name, variable_properties):
        """Add a new internal variable from a dict of properties (or legacy scalar)."""
        if 'internal_variables' not in self.active_config:
            self.active_config['internal_variables'] = {}

        if variable_name in self.active_config['internal_variables']:
            return False, f"Internal variable '{variable_name}' already exists.", self.active_config

        # Ensure variable_properties is a dict. If not, it implies an older call format or error.
        if not isinstance(variable_properties, dict):
            logger.error(f"add_internal_variable: variable_properties for '{variable_name}' is not a dict: {variable_properties}. Using defaults.")
            # Fallback to a very basic structure if properties are not a dict
            # This case should ideally be prevented by frontend validation or a stricter API contract.
            initial_val = variable_properties if isinstance(variable_properties, (int, float)) else 0
            default_variable = {
                'initial_value': initial_val, # Use the provided or defaulted initial_value
                'current_value': initial_val, # Current value starts at initial
                'min_value': variable_properties.get('min_value'), # None if not provided
                'max_value': variable_properties.get('max_value'), # None if not provided
                'step_value': variable_properties.get('step_value'), # None if not provided
                'on_change_osc': {
                    'enabled': False,
                    'address': f'/internal/variable/{variable_name}', # Default address
                    'value_type': 'float',
                    'value_content': 'value' # Send the actual variable value by default
                }
            }
        else:
            # Properties provided as a dictionary
            default_variable = {
                'initial_value': variable_properties.get('initial_value', 0),
                'current_value': variable_properties.get('initial_value', 0), # current starts at initial
                'min_value': variable_properties.get('min_value'), # Will be None if not provided
                'max_value': variable_properties.get('max_value'),
                'step_value': variable_properties.get('step_value'),
                'on_change_osc': variable_properties.get('on_change_osc', 
                                                       {"enabled": False, "address": f"/internal/{variable_name}", "value_type": "float", "value_content": "value"})
            }
            # Ensure numeric fields are numeric or None
            for key in ['initial_value', 'min_value', 'max_value', 'step_value']:
                if key in default_variable and default_variable[key] is not None:
                    try:
                        default_variable[key] = float(default_variable[key])
                    except (ValueError, TypeError):
                        logger.warning(f"Invalid numeric value for '{key}' in variable '{variable_name}'. Setting to None or default.")
                        if key == 'initial_value': default_variable[key] = 0; default_variable['current_value'] = 0
                        else: default_variable[key] = None

        self.active_config['internal_variables'][variable_name] = default_variable
        self.save_active_config()
        logger.debug(f"Added internal variable: {variable_name} with data {default_variable}")
        return True, f"Internal variable '{variable_name}' added successfully.", self.active_config

    def update_internal_variable(self, variable_name, variable_data_to_update):
        """Update properties of an existing internal variable by name."""
        if 'internal_variables' not in self.active_config or \
           variable_name not in self.active_config['internal_variables']:
            return False, f"Internal variable '{variable_name}' not found for update.", self.active_config

        if not isinstance(variable_data_to_update, dict):
            return False, "Data for update must be a dictionary.", self.active_config
        
        # Prevent changing the name via this method, though frontend shouldn't send 'name' in 'data' field.
        if 'name' in variable_data_to_update:
            del variable_data_to_update['name']

        existing_variable = self.active_config['internal_variables'][variable_name]
        
        # Properties that can be updated
        updatable_props = ['initial_value', 'min_value', 'max_value', 'step_value', 'on_change_osc']
        needs_save = False

        for prop, value in variable_data_to_update.items():
            if prop in updatable_props:
                if prop in ['initial_value', 'min_value', 'max_value', 'step_value']:
                    try:
                        # Allow None to clear optional fields, otherwise convert to float
                        new_val = float(value) if value is not None else None
                        if existing_variable.get(prop) != new_val:
                            existing_variable[prop] = new_val
                            needs_save = True
                    except (ValueError, TypeError):
                        logger.warning(f"Invalid numeric value '{value}' for '{prop}' in variable '{variable_name}'. Ignoring update for this field.")
                elif prop == 'on_change_osc': # on_change_osc is a dict itself
                    if isinstance(value, dict):
                        if existing_variable.get(prop) != value: # Simple dict comparison
                            existing_variable[prop] = value
                            needs_save = True
                    else:
                         logger.warning(f"Invalid value for 'on_change_osc' in variable '{variable_name}'. Expected dict, got {type(value)}. Ignoring.")
            else:
                logger.warning(f"Attempted to update unmanaged property '{prop}' for variable '{variable_name}'.")

        if needs_save:
            # TODO: Add validation (e.g., min_value < max_value if both are set)
            if (existing_variable.get('min_value') is not None and
                existing_variable.get('max_value') is not None and
                existing_variable['min_value'] >= existing_variable['max_value']):
                return False, "Min Value must be less than Max Value.", self.active_config

            self.save_active_config()
            logger.info(f"Updated internal variable: {variable_name} with {variable_data_to_update}")
            return True, f"Internal variable '{variable_name}' updated successfully.", self.active_config
        else:
            logger.info(f"No actual changes for internal variable: {variable_name}. Data received: {variable_data_to_update}")
            return True, f"No changes applied to internal variable '{variable_name}'.", self.active_config

    def delete_internal_variable(self, variable_name):
        """Delete an internal variable by name."""
        if 'internal_variables' not in self.active_config or \
           variable_name not in self.active_config['internal_variables']:
            return False, f"Internal variable '{variable_name}' not found for deletion.", self.active_config

        del self.active_config['internal_variables'][variable_name]
        logger.info(f"Deleted internal variable: {variable_name}")
        # TODO: Consider removing references from input mappings as done for channels
        self.save_active_config()
        return True, f"Internal variable '{variable_name}' deleted successfully.", self.active_config

    # --- Internal variable helpers used by processing/service layers ---
    def get_internal_variable_value(self, variable_name: str):
        """Return the current (or initial) value for a variable, or None."""
        vars_dict = self.active_config.get('internal_variables', {})
        var_cfg = vars_dict.get(variable_name)
        if not var_cfg:
            return None
        return var_cfg.get('current_value', var_cfg.get('initial_value', 0))

    def set_internal_variable_value(self, variable_name: str, value: float) -> bool:
        """Set and clamp a variable value, persisting configuration on change."""
        vars_dict = self.active_config.get('internal_variables', {})
        var_cfg = vars_dict.get(variable_name)
        if not var_cfg:
            logger.warning(f"set_internal_variable_value: variable '{variable_name}' not found.")
            return False
        # Clamp if min/max provided
        min_v = var_cfg.get('min_value')
        max_v = var_cfg.get('max_value')
        try:
            valf = float(value)
        except (ValueError, TypeError):
            logger.warning(f"set_internal_variable_value: invalid value '{value}' for '{variable_name}'.")
            return False
        if min_v is not None:
            try:
                valf = max(float(min_v), valf)
            except Exception:
                pass
        if max_v is not None:
            try:
                valf = min(float(max_v), valf)
            except Exception:
                pass
        previous = var_cfg.get('current_value', var_cfg.get('initial_value', 0))
        if previous == valf:
            return True
        var_cfg['current_value'] = valf
        self.save_active_config()
        return True

    # --- Input Mapping Methods ---
    def update_input_mapping(self, layer_id, input_name, mapping_data):
        """Create or replace an input mapping for a layer/input pair."""
        if 'layers' not in self.active_config or layer_id not in self.active_config['layers']:
            return False, f"Layer '{layer_id}' not found.", self.active_config
        
        layer = self.active_config['layers'][layer_id]
        if 'input_mappings' not in layer:
            layer['input_mappings'] = {}
            
        # Basic validation: mapping_data should be a dict.
        # More complex validation (e.g., valid target_type, action, params) can be added here or in a dedicated validator.
        if not isinstance(mapping_data, dict):
            logger.error(f"ConfigService: mapping_data for {layer_id}/{input_name} must be a dictionary. Received: {type(mapping_data)}")
            return False, "Mapping data must be a dictionary.", self.active_config

        layer['input_mappings'][input_name] = mapping_data
        self.save_active_config()
        logger.info(f"Updated input mapping for Layer '{layer_id}', Input '{input_name}' to: {mapping_data}")
        return True, f"Input mapping for '{input_name}' on Layer '{layer_id}' updated.", self.active_config

    def clear_input_mapping(self, layer_id, input_name):
        """Remove the mapping for a specific input in a layer, if present."""
        if layer_id in self.active_config.get('layers', {}) and \
           input_name in self.active_config['layers'][layer_id].get('input_mappings', {}):
            del self.active_config['layers'][layer_id]['input_mappings'][input_name]
            logger.info(f"Cleared input mapping for '{input_name}' in layer '{layer_id}'.")
            if self.save_active_config():
                return True, f"Mapping for '{input_name}' in layer '{layer_id}' cleared.", self.active_config
            else:
                return False, "Failed to save config after clearing mapping.", self.active_config
        return False, f"Mapping for '{input_name}' in layer '{layer_id}' not found.", self.active_config

    def clear_specific_channel_from_mapping(self, layer_id: str, input_name: str, channel_to_remove: str):
        """Remove one channel from an input's target list for a given layer.

        If that channel was the sole target, clear the mapping action and
        target to avoid leaving a broken mapping record.
        """
        layers = self.active_config.get('layers', {})
        if layer_id not in layers:
            return False, f"Layer '{layer_id}' not found.", self.active_config

        input_mappings = layers[layer_id].get('input_mappings', {})
        if input_name not in input_mappings:
            return False, f"Input '{input_name}' not found in layer '{layer_id}'.", self.active_config

        mapping_details = input_mappings[input_name]
        target_type = mapping_details.get('target_type')
        target_name = mapping_details.get('target_name')
        action = mapping_details.get('action')

        if target_type != 'osc_channel':
            return False, f"Mapping for '{input_name}' in layer '{layer_id}' is not an OSC channel mapping.", self.active_config

        modified = False
        if isinstance(target_name, str):
            if target_name == channel_to_remove:
                # If it's the only target, clear action and target
                mapping_details['target_name'] = None
                mapping_details['action'] = None
                # Potentially remove other params if they become irrelevant
                if 'params' in mapping_details:
                    del mapping_details['params']
                logger.info(f"Cleared target and action for OSC mapping '{input_name}' in layer '{layer_id}' as channel '{channel_to_remove}' was its only target.")
                modified = True
            else:
                # Target is a different single channel, no change
                pass
        elif isinstance(target_name, list):
            if channel_to_remove in target_name:
                target_name.remove(channel_to_remove)
                logger.info(f"Removed channel '{channel_to_remove}' from target list for '{input_name}' in layer '{layer_id}'. New targets: {target_name}")
                if not target_name: # List became empty
                    mapping_details['target_name'] = None
                    mapping_details['action'] = None
                    if 'params' in mapping_details:
                        del mapping_details['params']
                    logger.info(f"Target list for '{input_name}' in layer '{layer_id}' became empty; clearing action.")
                modified = True
        
        if modified:
            if mapping_details.get('action') is None and mapping_details.get('target_name') is None:
                # If the mapping is now effectively empty/invalid, remove it entirely.
                self.logger.info(f"Mapping for '{input_name}' in layer '{layer_id}' became empty after channel removal. Deleting the mapping entry.")
                del input_mappings[input_name]
            
            if self.save_active_config():
                return True, f"Channel '{channel_to_remove}' removed from mapping '{input_name}' in layer '{layer_id}'.", self.active_config
            else:
                return False, "Failed to save config after modifying mapping.", self.active_config
        else:
            return False, f"Channel '{channel_to_remove}' not found in mapping for '{input_name}' in layer '{layer_id}'.", self.active_config

    # --- Named Configuration Management ---

    def list_named_configs(self):
        """List saved configuration names (without .json) in the config directory."""
        if not os.path.exists(self.config_dir):
            return []
        try:
            files = [
                f for f in os.listdir(self.config_dir)
                if os.path.isfile(os.path.join(self.config_dir, f))
                and f.endswith('.json')
                and f not in [os.path.basename(self.active_config_path), os.path.basename(DEFAULT_CONFIG_FILE)]
            ]
            return sorted([os.path.splitext(f)[0] for f in files]) # Return names without .json
        except Exception as e:
            logger.error(f"Error listing named configurations: {e}")
            return []

    def save_as_named_config(self, name):
        """Save the current active configuration under a user-provided name."""
        if not name or not name.strip():
            logger.error("Cannot save configuration: name is empty.")
            return False, "Configuration name cannot be empty."
        # Sanitize name to prevent directory traversal or invalid characters
        safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '_', '-')).rstrip()
        if not safe_name:
            logger.error(f"Invalid configuration name provided: {name}. Use alphanumeric, spaces, hyphens, underscores.")
            return False, "Invalid characters in configuration name."
        
        file_path = os.path.join(self.config_dir, f"{safe_name}.json")
        if os.path.exists(file_path):
            logger.warning(f"Named configuration '{safe_name}.json' already exists. It will be overwritten.")
            # Optionally, ask for confirmation or prevent overwrite via a flag
        
        logger.info(f"Saving current active configuration as named config: {file_path}")
        if self.save_config_to_file(self.active_config, file_path):
            return True, f"Configuration '{safe_name}' saved successfully."
        else:
            return False, f"Failed to save configuration '{safe_name}'."

    def load_named_config(self, name):
        """Load a named configuration and persist it as the active configuration."""
        if not name or not name.strip():
            logger.error("Cannot load configuration: name is empty.")
            return False, "Configuration name cannot be empty."

        file_path = os.path.join(self.config_dir, f"{name}.json")
        if not os.path.exists(file_path):
            logger.error(f"Named configuration file not found: {file_path}")
            return False, f"Configuration '{name}' not found."

        loaded_config = self._load_config_from_file(file_path)
        if loaded_config:
            self.active_config = loaded_config
            self.save_active_config() # Save it as the new active config
            logger.info(f"Successfully loaded named configuration '{name}' as active config.")
            return True, f"Configuration '{name}' loaded successfully."
        else:
            logger.error(f"Failed to load or parse named configuration: {name}")
            return False, f"Failed to load or parse configuration '{name}'."

    def delete_named_config(self, name):
        """Delete a named configuration file from disk."""
        if not name or not name.strip():
            logger.error("Cannot delete configuration: name is empty.")
            return False, "Configuration name cannot be empty."

        file_path = os.path.join(self.config_dir, f"{name}.json")
        if not os.path.exists(file_path):
            logger.error(f"Named configuration file not found for deletion: {file_path}")
            return False, f"Configuration '{name}' not found."
        
        try:
            os.remove(file_path)
            logger.info(f"Successfully deleted named configuration: {file_path}")
            return True, f"Configuration '{name}' deleted successfully."
        except Exception as e:
            logger.error(f"Error deleting named configuration {file_path}: {e}")
            return False, f"Failed to delete configuration '{name}'."

    # --- Pub/Sub for config changes ---
    def subscribe_to_config_changes(self, callback):
        """Subscribe a no-arg callback to be called after config is saved."""
        if callback not in self._config_change_subscribers:
            self._config_change_subscribers.append(callback)
            logger.info(f"ConfigService: Callback {callback.__name__} subscribed to config changes.")

    def unsubscribe_from_config_changes(self, callback):
        """Remove a previously subscribed callback, if present."""
        try:
            self._config_change_subscribers.remove(callback)
            logger.info(f"ConfigService: Callback {callback.__name__} unsubscribed from config changes.")
        except ValueError:
            logger.warning(f"ConfigService: Callback {callback.__name__} not found in subscribers list for unsubscription.")

    def _notify_config_change_subscribers(self):
        """Invoke all registered subscribers after a successful save operation."""
        logger.debug(f"ConfigService: Notifying {len(self._config_change_subscribers)} subscribers of config change.")
        for callback in self._config_change_subscribers:
            try:
                callback() # Call the subscriber's registered method
            except Exception as e:
                logger.error(f"ConfigService: Error notifying subscriber {callback.__name__}: {e}")