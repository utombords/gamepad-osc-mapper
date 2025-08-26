"""Web service layer for Flask routes and Socket.IO events.

Serves the UI, exposes configuration CRUD over WebSockets, relays controller
status to the frontend, and coordinates updates across services on changes.
"""

import logging
from flask import render_template, current_app, request, jsonify
from flask_socketio import emit
import json
import os

logger = logging.getLogger(__name__)

# Path to the definitions file - define it once at module level
_DEFINITIONS_FILE_PATH = os.path.join(os.path.dirname(__file__), '..', 'definitions', 'input_mapping_definitions.json')

class WebService:
    """Bind Flask/Socket.IO to configuration, input, and OSC services."""
    def __init__(self, app_instance, socketio_instance, config_service_instance, osc_service_instance, input_service_instance):
        self.app = app_instance
        self.socketio = socketio_instance
        self.config_service = config_service_instance
        self.osc_service = osc_service_instance # Store OSCService instance
        self.input_service = input_service_instance # Store InputService instance
        self.logger = logger # Assign the module-level logger to the instance
        
        self.num_player_slots = 4 # Define the total number of player slots for the UI (primarily for XInput display)

        logger.info("WebService ready")
        self.register_routes()
        self.register_socketio_events()
        self._register_input_service_listeners() # Register for controller updates

    def register_routes(self):
        """Register HTTP routes used by the UI and health checks."""
        logger.debug("Registering routes")

        @self.app.route('/')
        def index():
            logger.debug("Serving index.html")
            return render_template('index.html')
        
        @self.app.route('/health')
        def health_check():
            logger.debug("Health check endpoint called")
            return "OK", 200

        @self.app.route('/api/input-mapping-definitions')
        def get_input_mapping_definitions():
            logger.debug("Serving input_mapping_definitions.json")
            try:
                # It's better to read the file each time to ensure freshness if it were ever to be hot-reloaded,
                # though for this use case, it's loaded once by ChannelProcessingService.
                # For simplicity and directness, we read it here.
                with open(_DEFINITIONS_FILE_PATH, 'r') as f:
                    definitions = json.load(f)
                return jsonify(definitions)
            except FileNotFoundError:
                logger.error(f"Input mapping definitions file not found at {_DEFINITIONS_FILE_PATH}")
                return jsonify({"error": "Input mapping definitions not found"}), 404
            except json.JSONDecodeError:
                logger.error(f"Failed to decode JSON from input mapping definitions file at {_DEFINITIONS_FILE_PATH}")
                return jsonify({"error": "Error decoding input mapping definitions"}), 500

    def _emit_active_config_update(self, target_sid=None):
        """Emit the full active configuration to one client or broadcast to all."""
        active_config = self.config_service.get_config()
        if target_sid:
            emit('active_config_updated', active_config, room=target_sid)
            logger.debug(f"Emitted active_config_updated to SID: {target_sid}")
        else:
            self.socketio.emit('active_config_updated', active_config)
            logger.debug("Broadcasted active_config_updated to all clients.")

    def register_socketio_events(self):
        """Register all Socket.IO event handlers for settings and mappings."""
        logger.debug("Registering Socket.IO configuration events")

        @self.socketio.on('connect')
        def handle_connect(*args):
            sid = request.sid
            logger.info(f'Client connected: {sid[:6]}…')


        @self.socketio.on('disconnect')
        def handle_disconnect(*args):
            sid = request.sid
            logger.info(f'Client disconnected: {sid[:6]}…')

        @self.socketio.on_error_default
        def default_error_handler(e):  # type: ignore[no-redef]
            # Log any unhandled exception in Socket.IO event handlers
            logger.error(f"Socket.IO handler error: {e}", exc_info=True)

        @self.socketio.on('get_active_config')
        def handle_get_active_config(*args):
            sid = request.sid
            logger.debug(f"get_active_config from {sid[:6]}…")
            self._emit_active_config_update(target_sid=sid)

        @self.socketio.on('list_configs')
        def handle_list_configs(*args):
            sid = request.sid
            logger.debug(f"list_configs from {sid[:6]}…")
            configs = self.config_service.list_named_configs()
            emit('configs_list', {'configs': configs}, room=sid)

        @self.socketio.on('load_named_config')
        def handle_load_named_config(data):
            sid = request.sid
            name = data.get('name')
            logger.info(f"load_config: '{name}' from {sid[:6]}…")
            success, message = self.config_service.load_named_config(name)
            if success:
                self._emit_active_config_update() # Broadcast to all clients
                emit('config_operation_status', {'success': True, 'message': message, 'action': 'load'}, room=sid)
            else:
                emit('config_operation_status', {'success': False, 'message': message, 'action': 'load'}, room=sid)

        @self.socketio.on('save_active_config_as')
        def handle_save_active_config_as(data):
            sid = request.sid
            name = data.get('name')
            logger.info(f"save_config_as: '{name}' from {sid[:6]}…")
            success, message = self.config_service.save_as_named_config(name)
            emit('config_operation_status', {'success': success, 'message': message, 'action': 'save_as'}, room=sid)
            if success:
                configs = self.config_service.list_named_configs()
                self.socketio.emit('configs_list', {'configs': configs})

        @self.socketio.on('delete_named_config')
        def handle_delete_named_config(data):
            sid = request.sid
            name = data.get('name')
            logger.info(f"delete_config: '{name}' from {sid[:6]}…")
            success, message = self.config_service.delete_named_config(name)
            emit('config_operation_status', {'success': success, 'message': message, 'action': 'delete'}, room=sid)
            if success:
                configs = self.config_service.list_named_configs()
                self.socketio.emit('configs_list', {'configs': configs})

        @self.socketio.on('update_osc_settings')
        def handle_update_osc_settings(data):
            sid = request.sid
            logger.info(f"update_osc_settings from {sid[:6]}…")

            if data is not None and isinstance(data, dict) and data:
                success = self.config_service.update_config_section('osc_settings', data)
                if success:
                    self._emit_active_config_update()
                    emit('config_operation_status', {'success': True, 'message': 'OSC settings updated successfully.', 'action': 'update_osc_success'}, room=sid)
                    
                    if self.osc_service:
                        logger.debug("Notify OSCService to reload config")
                        self.osc_service.reload_config()
                    else:
                        logger.warning("WebService: OSCService not available to notify for config reload.")
                else:
                    emit('config_operation_status', {'success': False, 'message': 'Failed to update OSC settings in config file.', 'action': 'update_osc_fail_save'}, room=sid)
            else:
                logger.warning(f"WebService: Invalid or empty data received for update_osc_settings from SID {sid}. Data: {data!r}")
                emit('config_operation_status', {'success': False, 'message': 'No valid settings data provided for OSC update. Expected a non-empty dictionary.', 'action': 'update_osc_invalid_data'}, room=sid)
        
        @self.socketio.on('update_input_settings')
        def handle_update_input_settings(data):
            sid = request.sid
            logger.info(f"update_input_settings from {sid[:6]}…")

            if data is not None and isinstance(data, dict) and data:
                success = self.config_service.update_config_section('input_settings', data)
                if success:
                    self._emit_active_config_update() # Broadcast to all clients
                    emit('config_operation_status', {
                        'success': True, 
                        'message': 'Global input settings updated successfully.', 
                        'action': 'update_input_success'
                    }, room=sid)
                    
                    if self.input_service:
                        logger.debug("Notify InputService to reload config")
                        self.input_service.reload_config(data) # Pass the new input_settings directly
                    else:
                        logger.warning("WebService: InputService not available to notify for config reload.")
                else:
                    emit('config_operation_status', {
                        'success': False, 
                        'message': 'Failed to update input settings in config file.', 
                        'action': 'update_input_fail_save'
                    }, room=sid)
            else:
                logger.warning(f"WebService: Invalid or empty data received for update_input_settings from SID {sid}. Data: {data!r}")
                emit('config_operation_status', {
                    'success': False, 
                    'message': 'No valid data provided for input settings update. Expected a non-empty dictionary.', 
                    'action': 'update_input_invalid_data'
                }, room=sid)
        
        @self.socketio.on('update_web_settings')
        def handle_update_web_settings(data):
            sid = request.sid
            logger.info(f"update_web_settings from {sid[:6]}…")

            if data is not None and isinstance(data, dict) and data:
                host = data.get('host')
                port = data.get('port')
                if not isinstance(host, str) or not host.strip():
                    emit('config_operation_status', {'success': False, 'message': 'Invalid host.', 'action': 'update_web_invalid_data'}, room=sid)
                    return
                try:
                    port = int(port)
                except Exception:
                    emit('config_operation_status', {'success': False, 'message': 'Invalid port.', 'action': 'update_web_invalid_data'}, room=sid)
                    return

                success = self.config_service.update_config_section('web_settings', {'host': host.strip(), 'port': port})
                if success:
                    self._emit_active_config_update()
                    emit('config_operation_status', {'success': True, 'message': 'Web settings saved. Restart required to apply.', 'action': 'update_web_success'}, room=sid)
                else:
                    emit('config_operation_status', {'success': False, 'message': 'Failed to update Web settings in config file.', 'action': 'update_web_fail_save'}, room=sid)
            else:
                logger.warning(f"WebService: Invalid or empty data received for update_web_settings from SID {sid}. Data: {data!r}")
                emit('config_operation_status', {'success': False, 'message': 'No valid settings data provided for Web update. Expected a non-empty dictionary.', 'action': 'update_web_invalid_data'}, room=sid)
        
        # Legacy echo handler removed

        @self.socketio.on('add_variable')
        def handle_add_variable(data, *args):
            variable_name = data.get('name')
            variable_properties = data 
            sid = request.sid
            self.logger.info(f"add_variable: '{variable_name}' from {sid[:6]}…")
            if not variable_name:
                self.logger.error(f"WebService: Invalid data for add_variable from SID {sid}. Name missing.")
                self.socketio.emit('variable_operation_status', {'success': False, 'message': 'Variable name cannot be empty.'}, room=sid)
                return

            success, message, new_config = self.config_service.add_internal_variable(variable_name, variable_properties)
            if success:
                self.logger.debug(f"variable added: '{variable_name}'")
                self.socketio.emit('active_config_updated', new_config)
                self.socketio.emit('variable_operation_status', {'success': True, 'message': message, 'variable_name': variable_name, 'operation': 'add'}, room=sid)
            else:
                self.logger.error(f"WebService: Failed to add variable '{variable_name}'. Error: {message}")
                self.socketio.emit('variable_operation_status', {'success': False, 'message': message}, room=sid)

        @self.socketio.on('update_variable')
        def handle_update_variable(data, *args):
            variable_name = data.get('name')
            variable_data = data.get('data') 
            sid = request.sid
            self.logger.info(f"update_variable: '{variable_name}' from {sid[:6]}…")
            if not variable_name or not variable_data or 'initial_value' not in variable_data:
                self.logger.error(f"WebService: Invalid data for update_variable from SID {sid}. Name or data missing/invalid.")
                self.socketio.emit('variable_operation_status', {'success': False, 'message': 'Invalid data for variable update.'}, room=sid)
                return

            success, message, new_config = self.config_service.update_internal_variable(variable_name, variable_data)
            if success:
                self.logger.debug(f"variable updated: '{variable_name}'")
                self.socketio.emit('active_config_updated', new_config)
                self.socketio.emit('variable_operation_status', {'success': True, 'message': message, 'variable_name': variable_name, 'operation': 'update'}, room=sid)
            else:
                self.logger.error(f"WebService: Failed to update variable '{variable_name}'. Error: {message}")
                self.socketio.emit('variable_operation_status', {'success': False, 'message': message}, room=sid)

        @self.socketio.on('delete_variable')
        def handle_delete_variable(data, *args):
            variable_name = data.get('name')
            sid = request.sid
            self.logger.info(f"delete_variable: '{variable_name}' from {sid[:6]}…")
            if not variable_name:
                self.logger.error(f"WebService: Invalid data for delete_variable from SID {sid}. Name missing.")
                self.socketio.emit('variable_operation_status', {'success': False, 'message': 'Variable name missing.'}, room=sid)
                return

            success, message, new_config = self.config_service.delete_internal_variable(variable_name)
            if success:
                self.logger.debug(f"variable deleted: '{variable_name}'")
                self.socketio.emit('active_config_updated', new_config)
                self.socketio.emit('variable_operation_status', {'success': True, 'message': message, 'variable_name': variable_name, 'operation': 'delete'}, room=sid)
            else:
                self.logger.error(f"WebService: Failed to delete variable '{variable_name}'. Error: {message}")
                self.socketio.emit('variable_operation_status', {'success': False, 'message': message}, room=sid)

        @self.socketio.on('add_channel')
        def handle_add_channel(data, *args):
            channel_name = data.get('name')
            sid = request.sid
            self.logger.info(f"add_channel: '{channel_name}' from {sid[:6]}…")

            if not channel_name:
                self.logger.error(f"WebService: Invalid data for add_channel from SID {sid}. Name missing.")
                self.socketio.emit('channel_operation_status', {'success': False, 'message': 'Channel name cannot be empty.', 'operation': 'add'}, room=sid)
                return
            
            channel_properties = data 
            
            success, message, new_config = self.config_service.add_internal_channel(channel_properties)

            if success:
                self.logger.debug(f"channel added: '{channel_name}'")
                self.socketio.emit('active_config_updated', new_config) # Broadcast to all
                self.socketio.emit('channel_operation_status', {'success': True, 'message': message, 'channel_name': channel_name, 'operation': 'add'}, room=sid)
                if self.osc_service:
                    self.osc_service.reload_config()
            else:
                self.logger.error(f"WebService: Failed to add channel '{channel_name}'. Error: {message}")
                self.socketio.emit('channel_operation_status', {'success': False, 'message': message, 'operation': 'add'}, room=sid)


        @self.socketio.on('update_channel')
        def handle_update_channel(data, *args):
            channel_name = data.get('name')
            channel_data_to_update = data.get('data')
            sid = request.sid
            self.logger.info(f"update_channel: '{channel_name}' from {sid[:6]}…")

            if not channel_name or not channel_data_to_update:
                self.logger.error(f"WebService: Invalid data for update_channel from SID {sid}. Name or data_to_update missing.")
                self.socketio.emit('channel_operation_status', {'success': False, 'message': 'Invalid data for channel update. Name or properties to update missing.', 'operation': 'update'}, room=sid)
                return

            success, message, new_config = self.config_service.update_internal_channel(channel_name, channel_data_to_update)
            if success:
                self.logger.debug(f"channel updated: '{channel_name}'")
                self.socketio.emit('active_config_updated', new_config) # Broadcast to all
                self.socketio.emit('channel_operation_status', {'success': True, 'message': message, 'channel_name': channel_name, 'operation': 'update'}, room=sid)
                if self.osc_service:
                    self.osc_service.reload_config()
            else:
                self.logger.error(f"WebService: Failed to update channel '{channel_name}'. Error: {message}")
                self.socketio.emit('channel_operation_status', {'success': False, 'message': message, 'operation': 'update'}, room=sid)
        
        @self.socketio.on('delete_channel')
        def handle_delete_channel(data, *args):
            channel_name = data.get('name')
            sid = request.sid
            self.logger.info(f"delete_channel: '{channel_name}' from {sid[:6]}…")

            if not channel_name:
                self.logger.error(f"WebService: Invalid data for delete_channel from SID {sid}. Name missing.")
                self.socketio.emit('channel_operation_status', {'success': False, 'message': 'Channel name missing for deletion.', 'operation': 'delete'}, room=sid)
                return

            success, message, new_config = self.config_service.delete_internal_channel(channel_name)
            if success:
                self.logger.debug(f"channel deleted: '{channel_name}'")
                self.socketio.emit('active_config_updated', new_config) # Broadcast to all
                self.socketio.emit('channel_operation_status', {'success': True, 'message': message, 'channel_name': channel_name, 'operation': 'delete'}, room=sid)
                if self.osc_service:
                    self.osc_service.reload_config()
            else:
                self.logger.error(f"WebService: Failed to delete channel '{channel_name}'. Error: {message}")
                self.socketio.emit('channel_operation_status', {'success': False, 'message': message, 'channel_name': channel_name, 'operation': 'delete'}, room=sid)

        # --------------- Input Mapping Handlers --------------- 
        @self.socketio.on('update_input_mapping')
        def handle_update_input_mapping(data, *args):
            sid = request.sid
            layer_id = data.get('layer_id')
            input_name = data.get('input_name')
            mapping_data = data.get('mapping_data')
            save_to_all_layers = data.get('save_to_all_layers', False)
            
            self.logger.info(f"update_input_mapping: layer={layer_id} input={input_name} save_all={save_to_all_layers}")

            if not all([layer_id, input_name, mapping_data is not None]):
                self.logger.error(f"WebService: Invalid data for update_input_mapping from SID {sid}. Missing layer_id, input_name, or mapping_data.")
                emit('mapping_operation_status', {
                    'success': False, 
                    'message': 'Invalid data: layer_id, input_name, and mapping_data are required.',
                    'layer_id': layer_id,
                    'input_name': input_name
                }, room=sid)
                return

            overall_success = True
            final_message = ""
            final_config_to_broadcast = None

            if save_to_all_layers:
                all_layers_dict = self.config_service.get_config().get('layers', {})
                target_layer_ids = list(all_layers_dict.keys())
                self.logger.info(f"WebService: Applying mapping for '{input_name}' to all layers: {target_layer_ids}")
                for current_layer_id in target_layer_ids:
                    success, message, new_config = self.config_service.update_input_mapping(current_layer_id, input_name, mapping_data)
                    if not success:
                        overall_success = False
                        final_message += f"Failed for layer {current_layer_id}: {message} "
                    else:
                        # Keep the config from the last successful update for broadcast
                        final_config_to_broadcast = new_config 
                if overall_success:
                    final_message = f"Input mapping for '{input_name}' updated across all layers."
                else:
                    final_message = f"Input mapping update for '{input_name}' had issues: {final_message.strip()}"
            else:
                success, message, new_config = self.config_service.update_input_mapping(layer_id, input_name, mapping_data)
                overall_success = success
                final_message = message
                if success:
                    final_config_to_broadcast = new_config

            if overall_success:
                self.logger.debug("input mapping updated")
                if final_config_to_broadcast: # Ensure there is a config to broadcast
                    self._emit_active_config_update() # Broadcast based on the latest state from ConfigService
                else: # Should not happen if overall_success is true from a single update
                    self.logger.warning("WebService: overall_success is true but final_config_to_broadcast is None. Fetching fresh config.")
                    self._emit_active_config_update()
                
                emit('mapping_operation_status', {
                    'success': True, 
                    'message': final_message, 
                    'layer_id': layer_id, # Original layer_id for context, even if all_layers
                    'input_name': input_name,
                    'operation': 'update'
                }, room=sid)
                if self.input_service:
                    self.input_service.reload_config() 
            else:
                self.logger.error(f"WebService: Failed input mapping operation. Message: {final_message}")
                emit('mapping_operation_status', {
                    'success': False, 
                    'message': final_message,
                    'layer_id': layer_id,
                    'input_name': input_name,
                    'operation': 'update_fail'
                }, room=sid)

        @self.socketio.on('clear_input_mapping')
        def handle_clear_input_mapping(data, *args):
            sid = request.sid
            layer_id = data.get('layer_id')
            input_name = data.get('input_name')
            save_to_all_layers = data.get('save_to_all_layers', False)

            self.logger.info(f"clear_input_mapping: layer={layer_id} input={input_name} save_all={save_to_all_layers}")

            if not all([layer_id, input_name]):
                self.logger.error(f"WebService: Invalid data for clear_input_mapping from SID {sid}. Missing layer_id or input_name.")
                emit('mapping_operation_status', {
                    'success': False, 
                    'message': 'Invalid data: layer_id and input_name are required.',
                    'layer_id': layer_id,
                    'input_name': input_name
                }, room=sid)
                return

            overall_success = True
            final_message = ""
            final_config_to_broadcast = None

            if save_to_all_layers:
                all_layers_dict = self.config_service.get_config().get('layers', {})
                target_layer_ids = list(all_layers_dict.keys())
                self.logger.info(f"WebService: Clearing mapping for '{input_name}' from all layers: {target_layer_ids}")
                success_count = 0
                not_found_count = 0
                for current_layer_id in target_layer_ids:
                    success, message, new_config = self.config_service.clear_input_mapping(current_layer_id, input_name)
                    if success:
                        success_count += 1
                        if new_config:
                            final_config_to_broadcast = new_config
                    else:
                        # Treat 'not found' as neutral when clearing across all layers
                        if isinstance(message, str) and ('not found' in message.lower()):
                            self.logger.info(f"Mapping for '{input_name}' not found on layer '{current_layer_id}', acceptable for 'clear all'.")
                            not_found_count += 1
                        else:
                            overall_success = False
                            final_message += f"Failed for layer {current_layer_id}: {message} "

                # Decide overall outcome
                if success_count > 0:
                    overall_success = True and overall_success
                    final_message = f"Input mapping for '{input_name}' cleared from all layers where present."
                elif not_found_count == len(target_layer_ids):
                    # Nothing to clear anywhere – consider this a successful no-op
                    overall_success = True
                    final_message = f"Input mapping for '{input_name}' did not exist on any layer."
                else:
                    overall_success = False
                    final_message = f"Input mapping clear for '{input_name}' had issues: {final_message.strip()}"
            else:
                success, message, new_config = self.config_service.clear_input_mapping(layer_id, input_name)
                overall_success = success
                final_message = message
                if success:
                    final_config_to_broadcast = new_config
            
            if overall_success:
                self.logger.info(f"WebService: Input mapping clear operation successful. Message: {final_message}. Broadcasting config update.")
                if final_config_to_broadcast: 
                    self._emit_active_config_update()
                else: # If all were 'not found' and new_config stayed None, still need to broadcast current state
                    self.logger.debug("clear_all: nothing to broadcast; sending fresh config")
                    self._emit_active_config_update()

                emit('mapping_operation_status', {
                    'success': True, 
                    'message': final_message, 
                    'layer_id': layer_id, 
                    'input_name': input_name,
                    'operation': 'clear'
                }, room=sid)
                if self.input_service:
                    self.input_service.reload_config()
            else:
                self.logger.error(f"WebService: Failed input mapping clear operation. Message: {final_message}")
                emit('mapping_operation_status', {
                    'success': False, 
                    'message': final_message,
                    'layer_id': layer_id,
                    'input_name': input_name,
                    'operation': 'clear_fail'
                }, room=sid)
        # --------------- End Input Mapping Handlers ---------------

        # 'active_layer_changed' local handler removed; CPS no longer emits it

        @self.socketio.on('get_controller_status')
        def handle_get_controller_status(*args):
            sid = request.sid
            logger.debug(f"get_controller_status from {sid[:6]}…")
            self._broadcast_controller_status_update(target_sid=sid)

        @self.socketio.on('jsl_rescan_controllers')
        def handle_jsl_rescan_controllers(*args):
            sid = request.sid
            self.logger.info("jsl_rescan_controllers")
            if self.input_service:
                result = self.input_service.jsl_rescan_controllers_action()
                # InputService already emits jsl_rescan_status if socketio is available to it
                # We can emit an additional confirmation or rely on InputService's emission.
                # For now, just log and let InputService handle direct feedback.
                self.logger.debug(f"jsl_rescan result: {result}")
                # Optionally, emit a more generic ack here if needed, e.g.:
                # emit('jsl_action_ack', {'action': 'rescan', 'status': result.get('status')}, room=sid)
            else:
                self.logger.error("WebService: InputService not available for jsl_rescan_controllers.")
                emit('jsl_action_ack', {'action': 'rescan', 'status': 'error', 'message': 'InputService unavailable'}, room=sid)

        @self.socketio.on('jsl_disconnect_all_controllers')
        def handle_jsl_disconnect_all_controllers(*args):
            sid = request.sid
            self.logger.info("jsl_disconnect_all_controllers")
            if self.input_service:
                result = self.input_service.jsl_disconnect_all_controllers_action()
                # Similar to rescan, InputService can handle emitting its own status.
                self.logger.debug(f"jsl_disconnect_all result: {result}")
                # Optionally, emit an ack:
                # emit('jsl_action_ack', {'action': 'disconnect_all', 'status': result.get('status')}, room=sid)
            else:
                self.logger.error("WebService: InputService not available for jsl_disconnect_all_controllers.")
                emit('jsl_action_ack', {'action': 'disconnect_all', 'status': 'error', 'message': 'InputService unavailable'}, room=sid)

        @self.socketio.on('jsl_device_update')
        def handle_jsl_device_update(data):
            sid = request.sid
            logger.debug("jsl_device_update")
            # This is just an example, actual event from InputService/JSLService might be different.
            self.socketio.emit('jsl_device_update', data)

        @self.socketio.on('clear_specific_mapping')
        def handle_clear_specific_mapping(data):
            sid = request.sid
            layer_id = data.get('layer_id')
            input_name = data.get('input_name')
            channel_to_remove = data.get('channel_name') # From the client, this is the channel being untargeted
            currently_editing_channel = data.get('currently_editing_channel') # For context, not directly used in logic here

            self.logger.info(f"clear_specific_mapping: layer={layer_id} input={input_name} channel={channel_to_remove}")

            if not all([layer_id, input_name, channel_to_remove]):
                self.logger.error(f"WebService: Invalid data for clear_specific_mapping from SID {sid}. Missing required fields.")
                # Optionally, emit a status back to the client
                emit('config_operation_status', {
                    'success': False, 
                    'message': 'Invalid data for clearing specific mapping. Required fields missing.',
                    'action': 'clear_specific_mapping_fail_data'
                }, room=sid)
                return

            success, message, new_config = self.config_service.clear_specific_channel_from_mapping(
                layer_id, input_name, channel_to_remove
            )

            if success:
                self.logger.info(f"WebService: Specific mapping cleared for Layer '{layer_id}', Input '{input_name}', Channel '{channel_to_remove}'. Broadcasting config update.")
                # ConfigService.save_active_config() (called by clear_specific_channel_from_mapping) will notify subscribers,
                # which should include ChannelProcessingService. WebService broadcasts the new config.
                self.socketio.emit('active_config_updated', new_config) 
                # Do not emit separate config_operation_status success message to avoid UI noise
            else:
                self.logger.error(f"WebService: Failed to clear specific mapping. Error: {message}")
                emit('config_operation_status', {
                    'success': False, 
                    'message': message,
                    'action': 'clear_specific_mapping_fail_logic'
                }, room=sid)

        self.logger.debug("Socket.IO events registered") 

    # --- Input Service Listeners --- 
    def _register_input_service_listeners(self):
        """Subscribe to input service events to reflect device status in UI."""
        if self.input_service:
            self.input_service.register_connect_listener(self.handle_controller_connect)
            self.input_service.register_disconnect_listener(self.handle_controller_disconnect)
            self.input_service.register_battery_listener(self.handle_battery_update) # Register battery listener
            logger.debug("Registered input listeners")
        else:
            logger.warning("WebService: InputService not available, cannot register listeners.")

    def handle_controller_connect(self, controller_id, controller_type_str, device_details):
        """Handle a controller connect by broadcasting status to clients."""
        logger.info(f"controller_connected: {controller_id} ({controller_type_str})")
        self._broadcast_controller_status_update()

    def handle_controller_disconnect(self, controller_id):
        """Handle a controller disconnect by broadcasting status to clients."""
        logger.info(f"controller_disconnected: {controller_id}")
        self._broadcast_controller_status_update()
    
    def handle_battery_update(self, controller_id: str, battery_info: tuple):
        """On battery update, publish updated controller status to clients."""
        logger.debug(f"battery_update: {controller_id}")
        self._broadcast_controller_status_update()

    def get_current_controller_status_payload(self):
        """Build the current controller status payload expected by the frontend."""
        if not self.input_service:
            logger.error("WebService: InputService not available in get_current_controller_status_payload.")
            # Return structure expected by frontend, but empty
            return {
                "xinput_slots": [
                    {"occupied": False, "slot_id_display": f"X{i}", "controller_id": None, "type_str": None, "battery_level_str": None, "battery_type_str": None} 
                    for i in range(self.num_player_slots)
                ],
                "jsl_devices": [],
                "active_controllers_count": 0
            }
        logger.debug("build_controller_status_payload")
        all_connected_raw = self.input_service.get_connected_controllers_status()
        logger.debug(f"connected_raw_count={len(all_connected_raw)}")
        
        # Initialize xinput_slots payload (for X0-X3)
        xinput_slots_payload = [
            {"occupied": False, "slot_id_display": f"X{i}", "controller_id": None, "type_str": None, "battery_level_str": "N/A", "battery_type_str": "N/A"} 
            for i in range(self.num_player_slots)
        ]
        jsl_devices_payload = []

        active_controllers_count = len(all_connected_raw)

        for controller_raw_data in all_connected_raw:
            if controller_raw_data.get("source") == "xinput":
                user_index = controller_raw_data.get("details", {}).get("user_index")
                if user_index is not None and 0 <= user_index < self.num_player_slots:
                    xinput_slots_payload[user_index] = {
                    "occupied": True,
                        "slot_id_display": f"X{user_index}",
                        "controller_id": controller_raw_data.get("id"),
                        "type_str": controller_raw_data.get("type"),
                        "battery_level_str": controller_raw_data.get("battery_level", "N/A"),
                        "battery_type_str": controller_raw_data.get("battery_type", "N/A"),
                        # Add any other details globalStatusView might use from xinput_slots[i]
                    }
                else:
                    logger.warning(f"XInput {controller_raw_data.get('id')} invalid user_index={user_index}")
                    # Optionally, could add it to a generic list if UI can handle more than 4 XInput somehow
            
            elif controller_raw_data.get("source") == "jsl":
                # For JSL, we just pass their data along. globalStatusView.js handles P0, P1, etc. display.
                jsl_devices_payload.append({
                    "occupied": True, # Implicitly true as it's in the connected list
                    "controller_id": controller_raw_data.get("id"),
                    "type_str": controller_raw_data.get("type"),
                    "battery_level_str": controller_raw_data.get("battery_level", "N/A"), # JSL usually N/A
                    "battery_type_str": controller_raw_data.get("battery_type", "N/A"),  # JSL usually N/A
                    "handle": controller_raw_data.get("details", {}).get("handle"), # Access handle from details. JSL specific detail
                    # slot_id_display is determined by globalStatusView for JSL P0, P1...
                })
        
        logger.debug(f"xinput_slots={xinput_slots_payload}; jsl_count={len(jsl_devices_payload)}")
        return {
            "xinput_slots": xinput_slots_payload,
            "jsl_devices": jsl_devices_payload,
            "active_controllers_count": active_controllers_count
        }

    def _broadcast_controller_status_update(self, target_sid=None):
        """Emit a consolidated controller status payload to one or all clients."""
        payload = self.get_current_controller_status_payload()
        event_name = 'controller_status_update'
        
        # Create a summary for logging to avoid overly long log messages
        payload_summary = {
            "xinput_slots_occupied": [s.get('occupied', False) for s in payload.get("xinput_slots", [])],
            "jsl_devices_count": len(payload.get("jsl_devices", [])),
            "active_controllers_count": payload.get("active_controllers_count", 0)
        }
        
        if target_sid:
            self.socketio.emit(event_name, payload, room=target_sid)
            self.logger.debug(f"emit {event_name} -> {target_sid[:6]}… summary={payload_summary}")
        else:
            self.socketio.emit(event_name, payload)
            self.logger.debug(f"broadcast {event_name} summary={payload_summary}")