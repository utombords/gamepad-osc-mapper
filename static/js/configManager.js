/**
 * ConfigManager: Client-side config state with simple pub/sub.
 */
window.App = window.App || {};
// const App = window.App;

// Manages the client-side state of the application configuration

App.ConfigManager = (function() {
    'use strict';
    let _config = {}; // Internal store for the main application configuration object.
    let _activeUiLayerId = 'A'; // ID of the currently active UI layer (e.g., 'A', 'B'). Defaults to 'A'.
    let _selectedInput = null;  // Name of the currently selected input for mapping (e.g., 'jsl_0_stick_x').

    // Pub/Sub mechanism for notifying other modules of changes.
    const _subscribers = {
        // eventName: [callback1, callback2, ...]
        // Supported eventTypes: 'configLoaded', 'configUpdated', 'activeUiLayerChanged', 'selectedInputChanged'.
    };

    /**
     * Notifies all subscribers for a given event type.
     * @param {string} eventType - The type of event to notify (e.g., 'configLoaded').
     * @param {any} data - The data to pass to subscriber callbacks.
     */
    function _notify(eventType, data) {
        if (_subscribers[eventType]) {
            _subscribers[eventType].forEach(callback => {
                try {
                    callback(data);
                } catch (e) {
                    console.error(`ConfigManager: Error in subscriber for event '${eventType}':`, e, {callbackData: data});
                }
            });
        }
    }

    /**
     * Creates a deep clone of an object using JSON stringify/parse.
     * @param {Object} obj - The object to clone.
     * @returns {Object} A deep clone of the object, or the original object if cloning fails.
     */
    function _deepClone(obj) {
        if (obj === null || typeof obj !== 'object') {
            return obj;
        }
        try {
            return JSON.parse(JSON.stringify(obj));
        } catch (e) {
            console.error("ConfigManager: Error during deep clone operation.", e, {objectToClone: obj});
            return obj; // Fallback to original object if JSON-based cloning fails.
        }
    }

    /**
     * Sets up subscriptions to SocketManager for configuration updates from the server
     * and requests the initial active configuration. This function is intended to be called
     * once SocketManager is connected.
     */
    function _initializeSubscriptions() {
        console.log("ConfigManager: SocketManager connected. Setting up config subscriptions and requesting initial config.");
        
        // Listen for updates to the active configuration from the server.
        App.SocketManager.on('active_config_updated', (newConfig) => {
            const oldConfig = _deepClone(_config);
            _config = _deepClone(newConfig); // Store a deep clone to prevent external modification.
            
            // Determine if this is the initial load or an update.
            if (Object.keys(oldConfig).length === 0 && Object.keys(_config).length > 0) {
                 _notify('configLoaded', _deepClone(_config));
            } else {
                // Avoid notifying if the new config is identical to the old one (can happen on redundant updates).
                if (JSON.stringify(oldConfig) !== JSON.stringify(_config)) {
                    _notify('configUpdated', { new: _deepClone(_config), old: oldConfig });
                }
            }
        });

        // Request the initial active configuration from the server.
        App.SocketManager.emit('get_active_config');
    }

    // --- Public API of the ConfigManager module ---
    return {
        /**
         * Initializes the ConfigManager.
         * Defers the setup of server communication (via _initializeSubscriptions)
         * until SocketManager reports a successful connection.
         */
        init: function() {
            console.log("ConfigManager: Initializing. Will wait for SocketManager connection to fetch config.");
            if (App.SocketManager && typeof App.SocketManager.onConnected === 'function') {
                App.SocketManager.onConnected(_initializeSubscriptions);
            } else {
                console.error("ConfigManager: SocketManager or SocketManager.onConnected not available. Configuration will not be loaded.");
            }
        },

        /**
         * Gets a deep clone of the current entire application configuration.
         * @returns {Object} A deep clone of the configuration object.
         */
        getConfig: function() { 
            return _deepClone(_config);
        },

        /** Gets a deep clone of the OSC settings section of the config. */
        getOscSettings: function() { return _deepClone(_config.osc_settings || {}); },
        /** Gets a deep clone of the global input settings section of the config. */
        getInputSettings: function() { return _deepClone(_config.input_settings || {}); },
        /** Gets a deep clone of the layers configuration. */
        getLayersConfig: function() { return _deepClone(_config.layers || {}); },

        /**
         * Retrieves a deep clone of a specific input mapping for a given layer and input ID.
         * @param {string} layerId - The ID of the layer (e.g., 'A').
         * @param {string} inputId - The ID of the input (e.g., 'jsl_0_stick_x').
         * @returns {Object} A deep clone of the mapping object, or an empty object if not found.
         */
        getMappingForInput: function(layerId, inputId) {
            if (_config && _config.layers && _config.layers[layerId] && 
                _config.layers[layerId].input_mappings && _config.layers[layerId].input_mappings[inputId]) {
                return _deepClone(_config.layers[layerId].input_mappings[inputId]);
            }
            return {}; // Return an empty object to avoid errors if mapping doesn't exist.
        },

        /** Gets the ID of the currently active UI layer. */
        getActiveUiLayerId: function() { return _activeUiLayerId; },
        /**
         * Sets the active UI layer ID and notifies subscribers if it changes.
         * Performs basic validation against standard layer IDs or loaded layer keys.
         * @param {string} layerId - The ID of the layer to set as active (e.g., 'A', 'B').
         */
        setActiveUiLayerId: function(layerId) {
            if (_activeUiLayerId !== layerId) {
                // Basic validation: check against known layer IDs or existing layer keys in loaded config.
                const standardLayers = ['A', 'B', 'C', 'D'];
                const configLayers = _config.layers ? Object.keys(_config.layers) : [];
                
                if (!standardLayers.includes(layerId) && !configLayers.includes(layerId)) {
                     console.warn(`ConfigManager: Attempt to set active UI layer to unknown ID: '${layerId}'. Current known layers: ${[...standardLayers, ...configLayers].join(', ')}. Proceeding, but UI might not reflect this correctly if tab doesn't exist.`);
                }

                _activeUiLayerId = layerId;
                _notify('activeUiLayerChanged', layerId);
            }
        },

        /** Gets the name of the currently selected input for mapping. */
        getSelectedInput: function() { return _selectedInput; },
        /**
         * Sets the currently selected input for mapping and notifies subscribers if it changes.
         * @param {string|null} inputName - The name of the input to select, or null to deselect.
         */
        setSelectedInput: function(inputName) {
            if (_selectedInput !== inputName) {
                _selectedInput = inputName;
                _notify('selectedInputChanged', inputName);
            }
        },
        
        /**
         * Subscribes a callback function to a specific event type.
         * @param {string} eventType - The event to subscribe to (e.g., 'configLoaded', 'configUpdated').
         * @param {Function} callback - The function to call when the event is triggered.
         * @returns {Function} An unsubscribe function. Calling this will remove the subscription.
         */
        subscribe: function(eventType, callback) {
            if (!eventType || typeof callback !== 'function') {
                console.error("ConfigManager.subscribe: eventType must be a non-empty string and callback must be a function.");
                return () => {}; // Return a no-op unsubscribe function for invalid inputs.
            }
            if (!_subscribers[eventType]) {
                _subscribers[eventType] = [];
            }
            if (_subscribers[eventType].includes(callback)) {
                console.warn(`ConfigManager.subscribe: Callback already registered for eventType '${eventType}'.`);
                // Still return a valid unsubscribe function for this specific instance if needed, though it might be redundant.
            }
            _subscribers[eventType].push(callback);

            return () => {
                if (_subscribers[eventType]) {
                    _subscribers[eventType] = _subscribers[eventType].filter(cb => cb !== callback);
                    if (_subscribers[eventType].length === 0) {
                        delete _subscribers[eventType]; // Clean up empty event arrays.
                    }
                }
            };
        },

        /**
         * Checks if the main configuration has been loaded from the server.
         * @returns {boolean} True if the config is loaded, false otherwise.
         */
        isConfigLoaded: function() {
            return _config && Object.keys(_config).length > 0;
        },

        /**
         * Sends a request to the server to update an input mapping.
         * Relies on the server to send back an 'active_config_updated' event to reflect changes locally.
         * @param {string} layerId - The ID of the layer for the mapping.
         * @param {string} inputId - The ID of the input to map.
         * @param {Object} mappingData - The new mapping configuration data.
         * @param {boolean} saveToAllLayers - Whether to apply this mapping to all layers.
         */
        updateInputMapping: function(layerId, inputId, mappingData, saveToAllLayers) {
            if (!App.SocketManager || !App.SocketManager.isConnected()) {
                console.error("ConfigManager.updateInputMapping: SocketManager not available or not connected. Cannot update mapping.");
                alert("Error: Not connected to server. Cannot update input mapping.");
                return;
            }
            
            App.SocketManager.emit('update_input_mapping', {
                layer_id: layerId,
                input_name: inputId,
                mapping_data: mappingData,
                save_to_all_layers: saveToAllLayers
            });
            // Note: ConfigManager relies on the server broadcasting 'active_config_updated'
            // to refresh its local _config and notify subscribers. No optimistic local update is performed here.
        }
        // Future granular config methods should emit to server, then rely on active_config_updated.
    };
})(); 