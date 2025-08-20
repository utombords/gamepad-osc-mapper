/**
 * GlobalStatusView: Manage status bar for XInput/JSL devices and actions.
 */

window.App = window.App || {};
// const App = window.App;

App.GlobalStatusView = (function() {
    'use strict';

    // DOM Element selectors and constants
    let statusBarContainer; // Main container for the status bar content.
    let jslRescanButton, jslDisconnectAllButton; // Buttons for JSL management.
    // let jslSlotsContainer; // No longer directly managed for individual slots in this new model

    // XInput slot elements - we will query them directly by ID
    const XINPUT_SLOT_ID_PREFIX = 'xinput-slot-';
    const NUM_XINPUT_SLOTS = 4;
    const PLAYER_SLOT_ID_PREFIX = 'player-slot-'; // Used for JSL P0, P1, P2 etc.
    const MAX_DYNAMIC_JSL_SLOTS = 16; // P0 is fixed, P1-P15 are dynamic

    // Store JSL device elements by their string ID (e.g., 'jsl_0') - This might be less relevant now
    // let _jslDeviceElements = {}; 

    let dynamicJslSlotsContainer; // Container for P1-P15

    /**
     * Handles the click event for the JSL Rescan button.
     * Emits a 'jsl_rescan_controllers' event to the server via SocketManager.
     */
    function _handleRescanJsl() {
        console.log("GlobalStatusView: JSL Rescan button clicked.");
        if (App.SocketManager && App.SocketManager.isConnected()) {
            App.SocketManager.emit('jsl_rescan_controllers');
        } else {
            alert("Error: Not connected to server. Cannot rescan controllers.");
            console.warn("GlobalStatusView: Cannot rescan JSL, SocketManager not connected.");
        }
    }

    /**
     * Handles the click event for the JSL Disconnect All button.
     * Confirms with the user and then emits a 'jsl_disconnect_all_controllers' event to the server.
     */
    function _handleDisconnectAllJsl() {
        console.log("GlobalStatusView: JSL Disconnect All button clicked.");
        if (confirm("Are you sure you want to disconnect all JoyShockLibrary controllers?")) {
            if (App.SocketManager && App.SocketManager.isConnected()) {
                App.SocketManager.emit('jsl_disconnect_all_controllers');
            } else {
                alert("Error: Not connected to server. Cannot disconnect controllers.");
                console.warn("GlobalStatusView: Cannot disconnect all JSL, SocketManager not connected.");
            }
        }
    }

    /**
     * Handles the 'jsl_rescan_status' event from the server.
     * Displays an alert if there was an error during the rescan process.
     * @param {Object} data - The status data from the server.
     * @param {string} data.status - 'success' or 'error'.
     * @param {string} [data.message] - An optional message, especially on error.
     */
    function _handleJslRescanStatus(data){
        console.log("GlobalStatusView: Received jsl_rescan_status", data);
        // Could update a general status message area if one exists
        // For now, just logging. User will see device slots update via _handleJslDeviceUpdate
        if (data.status === 'error'){
            alert(`JSL Rescan Error: ${data.message || 'Unknown error'}`);
        }
    }

    /**
     * Handles the 'jsl_disconnect_all_status' event from the server.
     * Displays an alert if there was an error during the disconnect all process.
     * @param {Object} data - The status data from the server.
     * @param {string} data.status - 'success' or 'error'.
     * @param {string} [data.message] - An optional message, especially on error.
     */
    function _handleJslDisconnectAllStatus(data){
        console.log("GlobalStatusView: Received jsl_disconnect_all_status", data);
        // Could update a general status message area
        if (data.status === 'error'){
            alert(`JSL Disconnect All Error: ${data.message || 'Unknown error'}`);
        } else {
            // Assume individual disconnect events will clear slots, or force clear here if needed
            // For now, rely on _handleJslDeviceUpdate for each disconnected device
        }
    }

    /**
     * Updates a single controller slot's DOM element with controller information.
     * Sets text content, title, CSS classes for connection status and battery level.
     * @param {HTMLElement} slotElement - The DOM element representing the controller slot.
     * @param {Object|null} controllerData - Data for the controller in this slot, or null if empty.
     * @param {string} defaultText - Default text for the slot if empty (e.g., "P0:", "X1:").
     * @param {string} [slotTypePrefix="P"] - The prefix for the slot type (e.g., "P" for JSL, "X" for XInput), used for display.
     */
    function _updateSlotDOM(slotElement, controllerData, defaultText, slotTypePrefix = "P") {
        if (!slotElement) {
            console.warn(`GlobalStatusView: _updateSlotDOM - slotElement is null for defaultText: ${defaultText}`);
            return;
        }
        
        // Clear previous status/battery classes
        const possibleStatusClasses = ['connected', 'disconnected', 'empty', 'status-good', 'status-error', 'status-neutral'];
        const possibleBatteryClassesPrefix = 'battery-bg-';
        slotElement.classList.remove(...possibleStatusClasses);
        Array.from(slotElement.classList).forEach(cls => {
            if (cls.startsWith(possibleBatteryClassesPrefix)) slotElement.classList.remove(cls);
        });

        if (controllerData && controllerData.occupied && controllerData.controller_id) {
            const idSuffix = controllerData.controller_id.replace("jsl_", "J").replace("xinput_", "X");
            slotElement.textContent = `${controllerData.slot_id_display || defaultText.split(':')[0]}: ${idSuffix}`;
            slotElement.title = `${controllerData.type_str || 'Controller'} (${controllerData.controller_id}) - Battery: ${controllerData.battery_level_str || 'N/A'}`;
            slotElement.classList.add('connected', 'status-good');
            slotElement.dataset.controllerId = controllerData.controller_id; 

            let batteryClass = 'battery-bg-unknown';
            const level = controllerData.battery_level_str ? controllerData.battery_level_str.toUpperCase() : 'UNKNOWN';
            const type = controllerData.battery_type_str ? controllerData.battery_type_str.toUpperCase() : 'UNKNOWN';

            if (controllerData.type_str && controllerData.type_str.toLowerCase().includes('pro controller')) {
                batteryClass = 'battery-bg-pro';
            } else if (type === 'WIRED') {
                batteryClass = 'battery-bg-wired';
            } else if (level === 'FULL' || level === 'HIGH') {
                batteryClass = 'battery-bg-full';
            } else if (level === 'MEDIUM') {
                batteryClass = 'battery-bg-medium';
            } else if (level === 'LOW' || level === 'CRITICAL') {
                batteryClass = 'battery-bg-low';
            } else if (level === 'EMPTY') {
                batteryClass = 'battery-bg-empty';
            } else if (level === 'CHARGING') { // JSL might report charging
                 batteryClass = 'battery-bg-wired'; // Use wired style for charging
            }
            slotElement.classList.add(batteryClass);
        } else {
            slotElement.textContent = defaultText;
            slotElement.title = `${defaultText.split(':')[0]} Slot`;
            slotElement.classList.add('disconnected', 'empty', 'status-neutral', 'battery-bg-disconnected');
            delete slotElement.dataset.controllerId; 
        }
    }

    /**
     * Handles the 'controller_status_update' event from the server.
     * This is a comprehensive update for all XInput and JSL controller slots.
     * Updates the DOM for each slot based on the received data.
     * @param {Object} data - The controller status data from the server.
     * @param {Array<Object|null>} data.xinput_slots - Array of XInput controller data (length NUM_XINPUT_SLOTS).
     * @param {Array<Object|null>} data.jsl_devices - Array of JSL controller data.
     */
    function _handleControllerStatusUpdate(data) {
        console.log("GlobalStatusView: Received controller_status_update RAW DATA:", data); // Log the raw data
        console.log("GlobalStatusView: typeof data.jsl_devices:", typeof data.jsl_devices, "Is Array?", Array.isArray(data.jsl_devices));
        if (Array.isArray(data.jsl_devices)) {
            console.log("GlobalStatusView: data.jsl_devices.length:", data.jsl_devices.length);
            data.jsl_devices.forEach((dev, index) => {
                console.log(`GlobalStatusView: jsl_devices[${index}]:`, dev);
            });
        }
        console.log("GlobalStatusView: Received controller_status_update (parsed once by me):", JSON.parse(JSON.stringify(data)));

        if (!data || !data.xinput_slots || !data.jsl_devices) {
            console.warn("GlobalStatusView: Invalid or missing xinput_slots or jsl_devices in controller_status_update data.");
            return;
        }

        // Update Fixed XInput Slots (X0-X3)
        for (let i = 0; i < NUM_XINPUT_SLOTS; i++) {
            const xinputSlotData = data.xinput_slots[i]; // Backend should send an array of 4, some might be null/empty
            const slotElement = document.getElementById(`${XINPUT_SLOT_ID_PREFIX}${i}`);
            if (slotElement) {
                _updateSlotDOM(slotElement, xinputSlotData, `X${i}:`, "X");
            } else {
                console.warn(`GlobalStatusView: XInput slot element ${XINPUT_SLOT_ID_PREFIX}${i} not found.`);
            }
        }

        // Update Fixed Primary JSL Slot (P0)
        const primaryJslSlotElement = document.getElementById(`${PLAYER_SLOT_ID_PREFIX}0`);
        if (primaryJslSlotElement) {
            const p0DeviceData = data.jsl_devices.length > 0 ? data.jsl_devices[0] : null;
            _updateSlotDOM(primaryJslSlotElement, p0DeviceData, "P0:", "P");
        } else {
            console.warn(`GlobalStatusView: Primary JSL slot element ${PLAYER_SLOT_ID_PREFIX}0 not found.`);
        }

        // Update Dynamic JSL Player Slots (P1-P15)
        if (!dynamicJslSlotsContainer) {
            console.warn("GlobalStatusView: dynamicJslSlotsContainer not found. Cannot update dynamic JSL slots.");
            return;
        }
        dynamicJslSlotsContainer.innerHTML = ''; // Clear previous dynamic slots

        // Start from the second JSL device for P1, up to MAX_DYNAMIC_JSL_SLOTS (P0 to P15 means 16 total)
        // So, we display data.jsl_devices[1] as P1, data.jsl_devices[2] as P2, ..., data.jsl_devices[15] as P15
        for (let i = 1; i < data.jsl_devices.length && i < MAX_DYNAMIC_JSL_SLOTS; i++) {
            const jslDeviceData = data.jsl_devices[i];
            const playerNumber = i; // P1, P2, ...

            let slotElement = document.getElementById(`${PLAYER_SLOT_ID_PREFIX}${playerNumber}`);
            if (!slotElement) {
                slotElement = document.createElement('div');
                slotElement.id = `${PLAYER_SLOT_ID_PREFIX}${playerNumber}`;
                slotElement.classList.add('status-slot', 'player-slot', 'controller-slot', 'controller-slot-indicator');
                dynamicJslSlotsContainer.appendChild(slotElement);
            }
            _updateSlotDOM(slotElement, jslDeviceData, `P${playerNumber}: Empty`, "P");
        }
    }

    // Public API of the GlobalStatusView module.
    return {
        /**
         * Initializes the GlobalStatusView module.
         * Caches DOM elements, sets up event listeners for JSL management buttons,
         * and subscribes to relevant SocketManager events for controller status updates.
         * Requests initial controller status upon connection.
         */
        init: function() {
            console.log("GlobalStatusView: Initializing...");
            statusBarContainer = document.getElementById('global-controller-status-bar-content');
            if (!statusBarContainer) {
                console.warn("GlobalStatusView: Status bar content container ('global-controller-status-bar-content') not found. Cannot initialize fully.");
            }

            jslRescanButton = document.getElementById('global-jsl-rescan-button');
            jslDisconnectAllButton = document.getElementById('global-jsl-disconnect-all-button');
            dynamicJslSlotsContainer = document.getElementById('dynamic-jsl-slots-container');

            if (!dynamicJslSlotsContainer) {
                 console.warn("GlobalStatusView: Dynamic JSL slots container ('dynamic-jsl-slots-container') not found!");
            }

            if (jslRescanButton) {
                jslRescanButton.addEventListener('click', _handleRescanJsl);
            } else {
                console.warn("GlobalStatusView: JSL Rescan button not found.");
            }

            if (jslDisconnectAllButton) {
                jslDisconnectAllButton.addEventListener('click', _handleDisconnectAllJsl);
            } else {
                console.warn("GlobalStatusView: JSL Disconnect All button not found.");
            }

            // TODO: Subscribe to SocketManager for JSL controller list updates
            // if (App.SocketManager) {
            //    App.SocketManager.on('jsl_controller_list_updated', _handleJslControllerListUpdate);
            // }
            if (App.SocketManager) {
                // Subscribe to per-device updates if server emits them
                if (typeof _handleJslDeviceUpdate === 'function') {
                    App.SocketManager.on('jsl_device_update', _handleJslDeviceUpdate);
                }
                if (typeof _handleXInputDeviceUpdate === 'function') {
                    App.SocketManager.on('xinput_device_update', _handleXInputDeviceUpdate);
                }
                App.SocketManager.on('jsl_rescan_status', _handleJslRescanStatus);
                App.SocketManager.on('jsl_disconnect_all_status', _handleJslDisconnectAllStatus);
                
                // New comprehensive status update listener
                App.SocketManager.on('controller_status_update', _handleControllerStatusUpdate);
                console.log("GlobalStatusView: Subscribed to JSL, XInput, and main controller_status_update events.");

                // Request initial status once connected
                App.SocketManager.onConnected(() => {
                    console.log("GlobalStatusView: SocketManager connected, requesting initial controller status.");
                    App.SocketManager.emit('get_controller_status'); 
                });

            } else {
                console.warn("GlobalStatusView: App.SocketManager not available at init. Cannot subscribe to device updates.");
            }

            console.log("GlobalStatusView: Initialization complete.");
        }
    };
})(); 