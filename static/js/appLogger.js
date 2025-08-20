/**
 * AppLogger: Centralized logger for selected SocketManager events.
 */

window.App = window.App || {}; // Ensure App namespace exists globally.

// console.log("appLogger.js: Script loaded."); // Can be enabled for load order debugging.

/**
 * @module App.AppLogger
 * @description Provides an `initialize` method to set up dedicated event loggers.
 * These loggers subscribe to various `App.SocketManager` events and output
 * formatted messages to the console, aiding in debugging and real-time monitoring of the application state.
 */
App.AppLogger = (() => {
    'use strict';

    /** Initialize listeners for selected events. Retries briefly if SocketManager not yet ready. */
    const initialize = () => {
        console.info("AppLogger: Attempting to initialize dedicated event loggers...");

        if (!window.App || !App.SocketManager || typeof App.SocketManager.on !== 'function') {
            console.warn("AppLogger: App.SocketManager not available or not fully initialized. Retrying in 500ms...");
            // Basic retry mechanism, as SocketManager might be initialized after AppLogger.
            setTimeout(initialize, 500);
            return;
        }

        console.info("AppLogger: SocketManager found. Attaching event listeners.");

        // --- Dedicated Event Loggers ---
        // These loggers provide insights into key application events transmitted over WebSockets.

        App.SocketManager.on('controller_status_update', (data) => {
            // Expect data to be an array, payload is typically data[0].
            const payload = data && Array.isArray(data) && data.length > 0 ? data[0] : data;
            console.info('[AppLogger] Event: controller_status_update', payload ? JSON.parse(JSON.stringify(payload)) : '(no payload)');
        });

        App.SocketManager.on('active_config_update', (config) => {
            console.info('[AppLogger] Event: active_config_update (Configuration received/updated).');
            // Avoid logging the entire (potentially large) config object by default.
            // For detailed debugging, uncomment the line below:
            // console.debug('[AppLogger] Full new config for active_config_update:', config);
        });
        
        // Listener for status of saving the active configuration.
        App.SocketManager.on('active_config_saved', (response) => { 
            if (response && response.status === 'success') {
                console.info(`[AppLogger] Event: active_config_saved - Success: ${response.message || 'Configuration saved.'}`);
            } else {
                console.error(`[AppLogger] Event: active_config_saved - Failed: ${response?.message || 'Unknown error'}`, response);
            }
        });

        // Listener for status of loading a named configuration file.
        App.SocketManager.on('config_loaded', (response) => { 
             if (response && response.status === 'success') {
                console.info(`[AppLogger] Event: config_loaded - Success: Named config '${response.filename || 'N/A'}' loaded. ${response.message || ''}`);
            } else {
                console.error(`[AppLogger] Event: config_loaded - Failed: ${response?.message || 'Unknown error loading named config.'}`, response);
            }
        });

        App.SocketManager.on('jsl_scan_complete', (data) => {
            const payload = data && Array.isArray(data) && data.length > 0 ? data[0] : data;
            console.info('[AppLogger] Event: jsl_scan_complete', payload || '(no payload)');
        });

        App.SocketManager.on('jsl_disconnect_all_status', (data) => {
            const payload = data && Array.isArray(data) && data.length > 0 ? data[0] : data;
            console.info('[AppLogger] Event: jsl_disconnect_all_status', payload || '(no payload)');
        });
        
        // Example: Log when the socket connects or disconnects via the manager
        App.SocketManager.on('connect', () => {
            console.info('[APP LOG] SocketManager reported: Connected.');
        });

        App.SocketManager.on('disconnect', (reason) => {
            console.warn('[APP LOG] SocketManager reported: Disconnected. Reason:', reason);
        });
        
        App.SocketManager.on('connect_error', (error) => {
            console.error('[APP LOG] SocketManager reported: Connection Error.', error);
        });


        // Add more specific loggers here for events you want to see by default.
        // For example, if you have specific error events from the backend:
        // App.SocketManager.on('backend_error_event_name', (errorDetails) => {
        //     console.error('[APP LOG] Backend Error:', errorDetails);
        // });

        console.info("AppLogger: All dedicated event loggers initialized and attached.");
    };

    return {
        initialize
    };
})(); 