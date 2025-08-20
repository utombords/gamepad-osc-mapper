/**
 * SettingsView: Manage Settings tab forms (OSC, Input, Web) and config IO.
 */

window.App = window.App || {};
// const App = window.App;

App.SettingsView = (function() {
    'use strict';

    const SETTINGS_TAB_ID = 'settings-tab'; // ID of the main settings tab container.

    // Module-level variables for DOM Elements related to OSC Server Settings.
    let oscServerIpInput, oscServerPortInput, oscServerUpdatesPerSecInput, oscLocalBindIpInput, oscUseBundlesCheckbox, saveOscSettingsButton;
    // Web server settings
    let webServerHostInput, webServerPortInput, saveWebSettingsButton;

    // Module-level variables for DOM Elements related to Global Input Settings.
    let stickDeadzoneInput, triggerDeadzoneInput, stickCurveInput, saveInputSettingsButton;
    let jslRescanIntervalInput, jslRescanPollingCheckbox;

    // Module-level variables for DOM Elements related to Configuration Management.
    let configListSelect, loadNamedConfigButton, deleteNamedConfigButton;
    let saveConfigNameInput, saveActiveConfigAsButton;

    // Placeholder for Controller Management Elements (e.g., rescan button).
    // let rescanControllersButton;

    /**
     * Populates the OSC server settings form fields with data from the provided settings object.
     * @param {Object} oscSettings - An object containing OSC server settings (ip, port, max_updates_per_second).
     */
    function _populateOscServerSettings(oscSettings) {
        if (!oscSettings) {
            console.warn("SettingsView: OSC settings data not provided to populate form.");
            return;
        }
        if (oscServerIpInput) oscServerIpInput.value = oscSettings.ip || '127.0.0.1';
        if (oscServerPortInput) oscServerPortInput.value = oscSettings.port || 9000;
        if (oscServerUpdatesPerSecInput) oscServerUpdatesPerSecInput.value = oscSettings.max_updates_per_second || 60;
        if (oscLocalBindIpInput) oscLocalBindIpInput.value = oscSettings.local_bind_ip || '';
        if (oscUseBundlesCheckbox) oscUseBundlesCheckbox.checked = !!oscSettings.use_bundles;
        console.log("SettingsView: OSC Server settings form populated.", oscSettings);
    }

    /**
     * Populates the global input settings form fields with data from the provided settings object.
     * @param {Object} inputSettings - An object containing global input settings (stick_deadzone, trigger_deadzone, stick_curve).
     */
    function _populateGlobalInputSettings(inputSettings) {
        if (!inputSettings) {
            console.warn("SettingsView: Input settings data not provided to populate form.");
            return;
        }
        if (stickDeadzoneInput) stickDeadzoneInput.value = inputSettings.stick_deadzone !== undefined ? inputSettings.stick_deadzone : 0.1;
        if (triggerDeadzoneInput) triggerDeadzoneInput.value = inputSettings.trigger_deadzone !== undefined ? inputSettings.trigger_deadzone : 0.05;
        if (stickCurveInput) stickCurveInput.value = inputSettings.stick_curve !== undefined ? String(inputSettings.stick_curve) : 'linear';
        
        // Populate JSL settings
        if (jslRescanIntervalInput) jslRescanIntervalInput.value = inputSettings.jsl_rescan_interval_s !== undefined ? inputSettings.jsl_rescan_interval_s : 30.0;
        if (jslRescanPollingCheckbox) jslRescanPollingCheckbox.checked = inputSettings.jsl_rescan_polling !== undefined ? inputSettings.jsl_rescan_polling : true;
        
        console.log("SettingsView: Global Input settings form populated.", inputSettings);
    }

    /**
     * Handles the click event for saving OSC server settings.
     * Gathers data from the form and emits an 'update_osc_settings' event to the server.
     */
    function _handleSaveOscSettings() {
        if (!App.SocketManager || !App.SocketManager.isConnected()) {
            console.error("SettingsView: SocketManager not available or not connected. Cannot save OSC settings.");
            alert("Error: Not connected to server. Cannot save OSC settings.");
            return;
        }
        const newOscSettings = {
            ip: oscServerIpInput ? oscServerIpInput.value : '127.0.0.1',
            port: oscServerPortInput ? parseInt(oscServerPortInput.value, 10) : 9000,
            max_updates_per_second: oscServerUpdatesPerSecInput ? parseInt(oscServerUpdatesPerSecInput.value, 10) : 60,
            local_bind_ip: oscLocalBindIpInput ? oscLocalBindIpInput.value.trim() : '',
            use_bundles: oscUseBundlesCheckbox ? !!oscUseBundlesCheckbox.checked : false
        };

        console.log("SettingsView: Attempting to save OSC settings:", newOscSettings);
        App.SocketManager.emit('update_osc_settings', newOscSettings);
    }

    function _handleSaveWebSettings() {
        if (!App.SocketManager || !App.SocketManager.isConnected()) {
            console.error('SettingsView: SocketManager not available or not connected. Cannot save Web settings.');
            alert('Error: Not connected to server. Cannot save Web settings.');
            return;
        }
        const newWebSettings = {
            host: webServerHostInput ? webServerHostInput.value : '127.0.0.1',
            port: webServerPortInput ? parseInt(webServerPortInput.value, 10) : 5000
        };
        console.log('SettingsView: Attempting to save Web settings:', newWebSettings);
        App.SocketManager.emit('update_web_settings', newWebSettings);
        alert('Web settings saved. Restart the app to apply changes.');
    }

    /**
     * Handles the click event for saving global input settings.
     * Gathers data from the form and emits an 'update_input_settings' event to the server.
     */
    function _handleSaveGlobalInputSettings() {
        if (!App.SocketManager || !App.SocketManager.isConnected()) {
            console.error("SettingsView: SocketManager not available or not connected. Cannot save Input settings.");
            alert("Error: Not connected to server. Cannot save Input settings.");
            return;
        }
        const newInputSettings = {
            stick_deadzone: stickDeadzoneInput ? parseFloat(stickDeadzoneInput.value) : 0.1,
            trigger_deadzone: triggerDeadzoneInput ? parseFloat(triggerDeadzoneInput.value) : 0.05,
            stick_curve: (stickCurveInput && stickCurveInput.value.trim() !== '') ? stickCurveInput.value.trim() : 'linear',
            // Add JSL settings
            jsl_rescan_interval_s: jslRescanIntervalInput ? parseFloat(jslRescanIntervalInput.value) : 30.0,
            jsl_rescan_polling: jslRescanPollingCheckbox ? jslRescanPollingCheckbox.checked : true
        };

        // Basic validation for jsl_rescan_interval_s
        if (newInputSettings.jsl_rescan_interval_s <= 0) {
            alert("JSL Rescan Interval must be a positive number.");
            if(jslRescanIntervalInput) jslRescanIntervalInput.focus();
            return;
        }

        console.log("SettingsView: Attempting to save Global Input settings:", newInputSettings);
        App.SocketManager.emit('update_input_settings', newInputSettings);
    }

    // --- Configuration Management Functions ---

    /**
     * Populates the dropdown list of saved configurations.
     * @param {string[]} configNamesArray - An array of configuration names.
     */
    function _populateConfigList(configNamesArray) {
        if (!configListSelect) {
            console.warn("SettingsView: Configuration list select element not found.");
            return;
        }
        const currentSelectedValue = configListSelect.value;
        configListSelect.innerHTML = '<option value="">-- Select a config to load or delete --</option>'; // Clear existing options.
        
        if (configNamesArray && configNamesArray.length > 0) {
            configNamesArray.forEach(name => {
                const option = document.createElement('option');
                option.value = name;
                option.textContent = name;
                configListSelect.appendChild(option);
            });
            // Try to reselect the previously selected value if it still exists in the new list.
            if (configNamesArray.includes(currentSelectedValue)) {
                configListSelect.value = currentSelectedValue;
            }
        }
        console.log("SettingsView: Config list populated:", configNamesArray);
    }

    /**
     * Handles the click event for loading a named configuration.
     * Emits a 'load_named_config' event to the server with the selected configuration name.
     */
    function _handleLoadNamedConfig() {
        if (!configListSelect || !App.SocketManager || !App.SocketManager.isConnected()) {
            alert("Error: Cannot load configuration. Server not connected or UI elements missing.");
            return;
        }
        const selectedName = configListSelect.value;
        if (!selectedName) {
            alert("Please select a configuration to load.");
            return;
        }
        console.log(`SettingsView: Requesting to load config: ${selectedName}`);
        App.SocketManager.emit('load_named_config', { name: selectedName });
    }

    /**
     * Handles the click event for deleting a named configuration.
     * Confirms with the user and emits a 'delete_named_config' event to the server.
     */
    function _handleDeleteNamedConfig() {
        if (!configListSelect || !App.SocketManager || !App.SocketManager.isConnected()) {
            alert("Error: Cannot delete configuration. Server not connected or UI elements missing.");
            return;
        }
        const selectedName = configListSelect.value;
        if (!selectedName) {
            alert("Please select a configuration to delete.");
            return;
        }
        if (confirm(`Are you sure you want to delete the configuration '${selectedName}'? This cannot be undone.`)) {
            console.log(`SettingsView: Requesting to delete config: ${selectedName}`);
            App.SocketManager.emit('delete_named_config', { name: selectedName });
        }
    }

    /**
     * Handles the click event for saving the active configuration under a new name.
     * Validates the name and emits a 'save_active_config_as' event to the server.
     */
    function _handleSaveActiveConfigAs() {
        if (!saveConfigNameInput || !App.SocketManager || !App.SocketManager.isConnected()) {
            alert("Error: Cannot save configuration. Server not connected or UI elements missing.");
            return;
        }
        const configName = saveConfigNameInput.value.trim();
        if (!configName) {
            alert("Please enter a name for the configuration file.");
            saveConfigNameInput.focus();
            return;
        }
        // Validate config name format (alphanumeric, underscores, hyphens).
        if (!/^[a-zA-Z0-9_\-]+$/.test(configName)) {
            alert("Invalid configuration name. Use only letters, numbers, underscores, or hyphens. No spaces or special characters.");
            saveConfigNameInput.focus();
            return;
        }
        console.log(`SettingsView: Requesting to save active config as: ${configName}`);
        App.SocketManager.emit('save_active_config_as', { name: configName });
        // Clearing the input field is now handled by _handleConfigOperationStatus on success.
    }

    /**
     * Requests an updated list of saved configurations from the server.
     * Emits a 'list_configs' event.
     */
    function _refreshConfigList() {
        if (App.SocketManager && App.SocketManager.isConnected()) {
            console.log("SettingsView: Requesting updated list of configurations.");
            App.SocketManager.emit('list_configs');
        } else {
            console.warn("SettingsView: Cannot refresh config list, SocketManager not connected.");
        }
    }
    
    /**
     * Handles the 'configs_list' event from the server, populating the config list dropdown.
     * @param {Object} data - The data object received from the server, expected to have a `configs` array.
     */
    function _handleConfigsList(data) {
        if (data && Array.isArray(data.configs)) {
            _populateConfigList(data.configs);
        } else {
            console.warn("SettingsView: Received malformed 'configs_list' data from server.", data);
            _populateConfigList([]); // Populate with an empty list to clear it visually.
        }
    }

    /**
     * Handles the 'config_operation_status' event from the server.
     * Displays status messages (success/failure) for configuration operations.
     * @param {Object} status - The status object from the server (action, success, message).
     */
    function _handleConfigOperationStatus(status) {
        console.log("SettingsView: Received config_operation_status:", status);
        if (status && status.message) {
            alert(`Config Operation: ${status.action}\nStatus: ${status.success ? 'Success' : 'Failed'}\nMessage: ${status.message}`);
        }
        if (status && status.success) {
            if (status.action === 'save_as') {
                if(saveConfigNameInput) saveConfigNameInput.value = ''; // Clear input on successful save.
                // The server typically broadcasts 'configs_list' after successful save/delete, so explicit refresh might not be needed here.
            }
            // Add similar handling for 'delete' if needed, though server broadcast is preferred.
        }
    }
    // --- End Configuration Management Functions ---

    /**
     * Callback function triggered when the main application configuration is loaded.
     * Populates settings forms and refreshes the list of named configurations.
     * @param {Object} config - The loaded application configuration object.
     */
    function _onConfigLoaded(config) {
        console.log("SettingsView: Received 'configLoaded' event from ConfigManager (or direct call).", config);
        if (config) {
            if (config.osc_settings) _populateOscServerSettings(config.osc_settings);
            if (config.input_settings) _populateGlobalInputSettings(config.input_settings);
            if (config.web_settings) {
                // Lazy-init Web DOM if not captured yet
                if (!webServerHostInput || !webServerPortInput) {
                    webServerHostInput = document.getElementById('setting-web-host');
                    webServerPortInput = document.getElementById('setting-web-port');
                }
                if (webServerHostInput && webServerPortInput) {
                    webServerHostInput.value = config.web_settings.host || '127.0.0.1';
                    webServerPortInput.value = config.web_settings.port || 5000;
                }
            }
        }
        // Always refresh the list of named configurations when the main config is loaded/reloaded.
        _refreshConfigList();
    }

    /**
     * Callback function triggered when the main application configuration is updated.
     * Re-populates relevant settings forms with the new configuration data.
     * @param {Object} update - An object containing the new configuration, typically { newConfig: Object }.
     */
    function _onConfigUpdated(update) {
        console.log("SettingsView: Received 'configUpdated' event from ConfigManager.", update);
        // This event comes from ConfigManager which gets it from active_config_updated from server.
        // It means the *active* config has changed. We should re-populate relevant fields.
        if (update && update.new) { // ConfigManager wraps it in 'new'
            if (update.new.osc_settings) _populateOscServerSettings(update.new.osc_settings);
            if (update.new.input_settings) _populateGlobalInputSettings(update.new.input_settings);
            if (update.new.web_settings) {
                if (!webServerHostInput || !webServerPortInput) {
                    webServerHostInput = document.getElementById('setting-web-host');
                    webServerPortInput = document.getElementById('setting-web-port');
                }
                if (webServerHostInput && webServerPortInput) {
                    webServerHostInput.value = update.new.web_settings.host || '127.0.0.1';
                    webServerPortInput.value = update.new.web_settings.port || 5000;
                }
            }
        }
    }

    /**
     * Initializes DOM element variables and event listeners for OSC server settings.
     */
    function _initOscServerSettings() {
        oscServerIpInput = document.getElementById('setting-osc-ip');
        oscServerPortInput = document.getElementById('setting-osc-port');
        oscServerUpdatesPerSecInput = document.getElementById('setting-osc-updates');
        oscLocalBindIpInput = document.getElementById('setting-osc-local-bind-ip');
        oscUseBundlesCheckbox = document.getElementById('setting-osc-use-bundles');
        saveOscSettingsButton = document.getElementById('save-osc-settings-button');

        if (saveOscSettingsButton) {
            saveOscSettingsButton.addEventListener('click', _handleSaveOscSettings);
        } else {
            console.warn("SettingsView: Save OSC Settings button not found.");
        }
    }

    function _initWebServerSettings() {
        webServerHostInput = document.getElementById('setting-web-host');
        webServerPortInput = document.getElementById('setting-web-port');
        saveWebSettingsButton = document.getElementById('save-web-settings-button');

        if (saveWebSettingsButton) {
            saveWebSettingsButton.addEventListener('click', _handleSaveWebSettings);
        } else {
            console.warn('SettingsView: Save Web Settings button not found.');
        }
    }

    /**
     * Initializes DOM element variables and event listeners for global input settings.
     */
    function _initGlobalInputSettings() {
        stickDeadzoneInput = document.getElementById('setting-input-stick-deadzone');
        triggerDeadzoneInput = document.getElementById('setting-input-trigger-deadzone');
        stickCurveInput = document.getElementById('setting-input-stick-curve');
        saveInputSettingsButton = document.getElementById('save-input-settings-button');

        // Initialize JSL setting elements
        jslRescanIntervalInput = document.getElementById('setting-jsl-rescan-interval');
        jslRescanPollingCheckbox = document.getElementById('setting-jsl-rescan-polling');

        if (saveInputSettingsButton) {
            saveInputSettingsButton.addEventListener('click', _handleSaveGlobalInputSettings);
        } else {
            console.warn("SettingsView: Save Input Settings button not found.");
        }

        if (!jslRescanIntervalInput) console.warn("SettingsView: JSL Rescan Interval input not found.");
        if (!jslRescanPollingCheckbox) console.warn("SettingsView: JSL Rescan Polling checkbox not found.");
    }

    /**
     * Initializes DOM element variables and event listeners for configuration management.
     */
    function _initConfigManagement() {
        configListSelect = document.getElementById('setting-config-list');
        loadNamedConfigButton = document.getElementById('load-named-config-button');
        deleteNamedConfigButton = document.getElementById('delete-named-config-button');
        saveConfigNameInput = document.getElementById('setting-save-config-name');
        saveActiveConfigAsButton = document.getElementById('save-active-config-as-button');

        if (loadNamedConfigButton) loadNamedConfigButton.addEventListener('click', _handleLoadNamedConfig);
        else console.warn("SettingsView: loadNamedConfigButton not found");

        if (deleteNamedConfigButton) deleteNamedConfigButton.addEventListener('click', _handleDeleteNamedConfig);
        else console.warn("SettingsView: deleteNamedConfigButton not found");
        
        if (saveActiveConfigAsButton) saveActiveConfigAsButton.addEventListener('click', _handleSaveActiveConfigAs);
        else console.warn("SettingsView: saveActiveConfigAsButton not found");

        if (!configListSelect) console.warn("SettingsView: configListSelect not found.");
        if (!saveConfigNameInput) console.warn("SettingsView: saveConfigNameInput not found.");
        
        console.log("SettingsView: Config Management UI Initialized.", {
            configListSelect: !!configListSelect,
            loadNamedConfigButton: !!loadNamedConfigButton,
            deleteNamedConfigButton: !!deleteNamedConfigButton,
            saveConfigNameInput: !!saveConfigNameInput,
            saveActiveConfigAsButton: !!saveActiveConfigAsButton
        });
    }
    
    // TODO: _initControllerManagement()

    return {
        /**
         * Initializes the SettingsView module.
         * Caches DOM elements, sets up event listeners for various settings sections,
         * and subscribes to relevant events from ConfigManager and SocketManager.
         */
        init: function() {
            console.log("SettingsView: Initializing...");
            const settingsTabPane = document.getElementById(SETTINGS_TAB_ID);
            if (!settingsTabPane) {
                console.warn("SettingsView: Settings tab pane not found. Cannot initialize.");
                return;
            }

            _initOscServerSettings();
            _initGlobalInputSettings();
            _initWebServerSettings();
            _initConfigManagement();
            // _initControllerManagement();

            if (App.ConfigManager) {
                App.ConfigManager.subscribe('configLoaded', _onConfigLoaded);
                App.ConfigManager.subscribe('configUpdated', _onConfigUpdated);
                console.log("SettingsView: Subscribed to ConfigManager events.");

                const currentConfig = App.ConfigManager.getConfig();
                if (currentConfig && Object.keys(currentConfig).length > 0) {
                     _onConfigLoaded(currentConfig); 
                } else {
                    console.log("SettingsView: ConfigManager available, but initial config not yet populated. Waiting for 'configLoaded' event.");
                }
            } else {
                console.warn("SettingsView: ConfigManager not available. Settings might not populate correctly.");
            }
            
            if(App.SocketManager) {
                App.SocketManager.on('configs_list', _handleConfigsList);
                App.SocketManager.on('config_operation_status', _handleConfigOperationStatus);
                console.log("SettingsView: Subscribed to SocketManager events for config lists and ops.");

                // Initial request for config list, if socket is ready.
                // If not ready, onConnected in ConfigManager will trigger _onConfigLoaded, which calls _refreshConfigList.
                if (App.SocketManager.isConnected()) {
                    _refreshConfigList();
                } else {
                    // It's also called in _onConfigLoaded, which is triggered by ConfigManager after socket connection
                    console.log("SettingsView: SocketManager not yet connected. Config list refresh will be triggered via ConfigManager post-connection.");
                }
            } else {
                console.warn("SettingsView: SocketManager not available to listen for config events.");
            }
            
            console.log("SettingsView: Initialization complete.");
        }
    };
})(); 