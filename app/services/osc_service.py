"""OSC message construction and sending.

Builds OSC messages and bundles using python-osc, expands variable placeholders
in addresses and string payloads, and provides basic rate-friendly batching.
"""
import logging
import time
import re
import socket

logger = logging.getLogger(__name__)

from pythonosc.udp_client import SimpleUDPClient
from pythonosc import osc_bundle_builder
from pythonosc.osc_message_builder import OscMessageBuilder
# from pythonosc.dispatcher import Dispatcher # If receiving OSC, not typically needed for a mapper

# Ensure logger level is set appropriately if not inherited
logger.setLevel(logging.INFO)  # Respect global default; DEBUG only when root level is DEBUG
logger.debug("OSC_SERVICE_MODULE: Logger configured (module logger level INFO; DEBUG requires root DEBUG).")

class OSCService:
    """High-level OSC sender bound to the application's configuration service."""
    def __init__(self, config_service_instance, socketio_instance=None):
        self.config_service = config_service_instance
        self.socketio = socketio_instance
        self.channel_processing_service = None
        self.osc_client = None
        self.message_queue = []
        self._suppress_var_expanded_channels_until = 0.0
        self._use_bundles = False
        logger.info("OSCService Initialized")
        self._setup_osc_client()

    def set_channel_processing_service(self, channel_processing_service_instance):
        self.channel_processing_service = channel_processing_service_instance
        logger.info("OSCService: ChannelProcessingService instance set.")
        # Example: if self.channel_processing_service and self.socketio:
        # self.socketio.emit('status', {'service': 'osc', 'message': 'CPS ready'})

    def _setup_osc_client(self):
        """(Re)create the UDP client from current OSC settings.

        Supports optional broadcast by setting osc_settings.allow_broadcast
        to true, or automatically when the destination address looks like a
        subnet or global broadcast (x.x.x.255 or 255.255.255.255).
        """
        osc_settings = self.config_service.get_osc_settings()
        ip = osc_settings.get('ip', '127.0.0.1')
        port = osc_settings.get('port', 9000)
        # Enable broadcast if explicitly requested or if the target appears to be a broadcast address
        broadcast_like = isinstance(ip, str) and (ip.endswith('.255') or ip == '255.255.255.255')
        allow_broadcast = bool(osc_settings.get('allow_broadcast', broadcast_like))
        try:
            self.osc_client = SimpleUDPClient(ip, port, allow_broadcast=allow_broadcast)
            logger.info(f"OSC client configured for {ip}:{port} (broadcast={'on' if allow_broadcast else 'off'}).")
            # In python-osc, the UDP client is ready after construction; no explicit connect
            # Optionally bind to a specific local interface to control the NIC used
            local_bind_ip = (osc_settings or {}).get('local_bind_ip')
            if isinstance(local_bind_ip, str):
                local_bind_ip = local_bind_ip.strip()
            if local_bind_ip and local_bind_ip != '0.0.0.0':
                try:
                    if hasattr(self.osc_client, '_sock') and isinstance(self.osc_client._sock, socket.socket):
                        # Bind to requested local interface using ephemeral port
                        self.osc_client._sock.bind((local_bind_ip, 0))
                        logger.info(f"OSC client bound to local interface {local_bind_ip} for outbound UDP.")
                    else:
                        logger.warning("OSC client socket not accessible for binding; skipping local_bind_ip.")
                except Exception as bind_err:
                    logger.error(f"Failed to bind OSC client to {local_bind_ip}: {bind_err}")
        except Exception as e:
            logger.error(f"Failed to initialize OSC client for {ip}:{port}: {e}")
            self.osc_client = None

    def reload_config(self):
        """Reload OSC settings and clear any queued messages."""
        logger.info("OSCService: Reloading OSC configuration.")
        self._setup_osc_client()
        # Update bundle preference from settings (default: False for compatibility)
        try:
            osc_settings = self.config_service.get_osc_settings() or {}
            self._use_bundles = bool(osc_settings.get('use_bundles', False))
        except Exception:
            self._use_bundles = False
        self.message_queue = [] # Clear queue on reload too

    def _build_osc_message(self, address, value, type_hint=None):
        """Build a python-osc message with an optional explicit type hint."""
        builder = OscMessageBuilder(address=address)
        if type_hint == 'int':
            builder.add_arg(int(value), 'i')
        elif type_hint == 'float':
            builder.add_arg(float(value), 'f')
        elif type_hint == 'string':
            builder.add_arg(str(value), 's')
        elif type_hint == 'bool': # OSC typically uses int 0 or 1 for bool
            builder.add_arg(1 if value else 0, 'i')
        elif isinstance(value, bool): # Auto-detect bool if no hint
            builder.add_arg(1 if value else 0, 'i')
        elif isinstance(value, int):
            builder.add_arg(value, 'i')
        elif isinstance(value, float):  
            builder.add_arg(value, 'f')
        elif isinstance(value, str):
            builder.add_arg(value, 's')
        else:
            # Default to float if type is unknown or not directly mappable, 
            # or let python-osc infer (which might default to string for some unhandled types)
            try:
                builder.add_arg(float(value), 'f')
            except (ValueError, TypeError):
                builder.add_arg(str(value), 's')
                logger.warning(f"OSC arg for {address}: Could not coerce {value} to float, sending as string.")
        
        built_msg = builder.build()
        return built_msg

    def handle_value_update(self, update_type, name, value):
        """Queue an OSC message for a channel or variable value update."""
        config = self.config_service.get_config()
        if not self.osc_client:
            logger.debug("OSC client not ready in handle_value_update, cannot queue message.")
            return

        osc_address = None
        osc_value_to_send = value
        value_type_hint = None

        if update_type == 'channel':
            channel_config = config.get('internal_channels', {}).get(name)
            if channel_config and channel_config.get('osc_address'):
                raw_addr = channel_config['osc_address']
                # Expand placeholders
                osc_address = self._expand_address_placeholders(raw_addr, config)
                # Optionally suppress channels whose address depends on variables shortly after a variable step
                if ('{' in raw_addr and '}' in raw_addr) and time.time() < self._suppress_var_expanded_channels_until:
                    logger.debug(f"Suppressing channel send for '{name}' due to recent variable update affecting address: {osc_address}")
                    return
                value_type_hint = channel_config.get('osc_type', 'float') # Default to float for channels
                # If this channel is configured as string type, pick from predefined strings
                if value_type_hint == 'string':
                    strings = channel_config.get('osc_strings')
                    if isinstance(strings, list) and len(strings) >= 1:
                        try:
                            fval = float(value)
                        except (ValueError, TypeError):
                            fval = 0.0
                        idx = 1 if fval >= 0.5 and len(strings) > 1 else 0
                        osc_value_to_send = strings[idx]
                # Expand placeholders inside string payloads using variables
                if value_type_hint == 'string' and isinstance(osc_value_to_send, str):
                    osc_value_to_send = self._expand_string_placeholders(osc_value_to_send, config)
        elif update_type == 'variable':
            var_config = config.get('internal_variables', {}).get(name)
            if var_config and var_config.get('on_change_osc', {}).get('enabled'):
                osc_settings_for_var = var_config['on_change_osc']
                osc_address = osc_settings_for_var.get('address')
                value_type_hint = osc_settings_for_var.get('value_type') # e.g., 'float', 'int', 'string', 'bool'
                
                # Check if a specific string content is defined, otherwise use the variable's runtime value
                fixed_value_content = osc_settings_for_var.get('value_content')
                if fixed_value_content is not None and fixed_value_content != '': # Treat empty string as "use variable value"
                    osc_value_to_send = fixed_value_content
                    if not value_type_hint: # If sending fixed content and no type hint, assume string
                        value_type_hint = 'string' 
                # Else, osc_value_to_send remains the passed 'value' of the variable

        if osc_address:
            try:
                message = self._build_osc_message(osc_address, osc_value_to_send, value_type_hint)
                self.message_queue.append(message)
            except Exception as e:
                logger.error(f"Error building or queuing OSC message for {osc_address} from handle_value_update: {e}", exc_info=True)
        else:
            logger.debug(f"No OSC address determined for {update_type} '{name}', not queueing.")

    def send_custom_osc_message(self, address, value, value_type_hint=None):
        """Queue a custom OSC message for later bundle send."""
        if not self.osc_client:
            logger.debug("OSC client not ready in send_custom_osc_message, cannot queue message.")
            return
        logger.debug(f"Queueing Custom OSC msg: Addr='{address}', Val='{value}', TypeHint='{value_type_hint}'")
        try:
            message = self._build_osc_message(address, value, value_type_hint)
            self.message_queue.append(message)
        except Exception as e:
            logger.error(f"Error building or queuing custom OSC message to {address}: {e}", exc_info=True)

    def send_bundled_messages(self):
        """Send any queued messages as a single OSC bundle, if a client exists."""
        if not self.osc_client:
            logger.warning("OSCService.send_bundled_messages: OSC client not initialized. Cannot send.")
            self.message_queue = [] # Clear queue to prevent buildup if client is broken
            return
        
        if not self.message_queue:
            return

        # Optionally send messages individually for receivers that don't support bundles
        if not self._use_bundles:
            try:
                for msg in self.message_queue:
                    self.osc_client.send(msg)
                logger.debug(f"Sent {len(self.message_queue)} OSC messages individually to {self.osc_client._address}:{self.osc_client._port}.")
            except Exception as e:
                logger.error(f"Error sending OSC messages individually to {self.osc_client._address}:{self.osc_client._port if self.osc_client else 'N/A'}: {e}", exc_info=True)
            finally:
                self.message_queue = []
            return

        bundle_builder = osc_bundle_builder.OscBundleBuilder(timestamp=osc_bundle_builder.IMMEDIATELY)
        for i, msg in enumerate(self.message_queue):
            bundle_builder.add_content(msg)
        
        try:
            bundle = bundle_builder.build()
            self.osc_client.send(bundle)
            logger.debug(f"Sent OSC bundle with {len(self.message_queue)} messages to {self.osc_client._address}:{self.osc_client._port}.")
        except Exception as e:
            logger.error(f"Error sending OSC bundle to {self.osc_client._address}:{self.osc_client._port if self.osc_client else 'N/A'}: {e}", exc_info=True)
        finally:
            self.message_queue = []

    # Add methods for handling specific OSC message sending based on configuration 

    def _expand_address_placeholders(self, address: str, config: dict) -> str:
        """Expand {variableName} placeholders in an OSC address using config vars."""
        if '{' not in address or '}' not in address:
            return address
        variables = config.get('internal_variables', {})

        def replace(match):
            key = match.group(1)
            var_cfg = variables.get(key)
            if var_cfg is None:
                return match.group(0)  # leave unchanged if not found
            val = var_cfg.get('current_value', var_cfg.get('initial_value', 0))
            try:
                # Format numbers without unnecessary decimals
                if isinstance(val, int):
                    return str(val)
                fv = float(val)
                if fv.is_integer():
                    return str(int(fv))
                return ('{0:g}'.format(fv))
            except Exception:
                return match.group(0)

        try:
            return re.sub(r"\{([A-Za-z0-9_]+)\}", replace, address)
        except Exception:
            return address

    def suppress_variable_expanded_channels(self, duration_seconds: float = 0.1):
        """Temporarily suppress sends for channels whose addresses use variables."""
        self._suppress_var_expanded_channels_until = max(
            self._suppress_var_expanded_channels_until,
            time.time() + max(0.0, duration_seconds)
        )

    def _expand_string_placeholders(self, text: str, config: dict) -> str:
        """Expand {variableName} placeholders inside string payloads."""
        if '{' not in text or '}' not in text:
            return text
        variables = config.get('internal_variables', {})

        def replace(match):
            key = match.group(1)
            var_cfg = variables.get(key)
            if var_cfg is None:
                return match.group(0)
            val = var_cfg.get('current_value', var_cfg.get('initial_value', 0))
            try:
                if isinstance(val, int):
                    return str(val)
                fv = float(val)
                if fv.is_integer():
                    return str(int(fv))
                return '{0:g}'.format(fv)
            except Exception:
                return str(val)

        try:
            return re.sub(r"\{([A-Za-z0-9_]+)\}", replace, text)
        except Exception:
            return text
