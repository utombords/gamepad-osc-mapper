/**
 * mainApp: Frontend entry. Initializes core modules after DOM is ready.
 */
window.App = window.App || {}; // Ensure App namespace exists globally.

document.addEventListener('DOMContentLoaded', () => {
    'use strict';
    console.log("App: Initializing modules...");

    // Ensure App namespace exists, though it should have been by the line above.
    window.App = window.App || {};

    // --- Core Module Initializations ---
    // The order of initialization can be important if modules have dependencies on each other.

    // 1. Initialize SocketManager first as it handles server communication.
    if (App.SocketManager && typeof App.SocketManager.init === 'function') {
            App.SocketManager.init();
    } else {
        console.error("mainApp.js: App.SocketManager not found or init method missing. Application may not function.");
        // Early exit or error display might be appropriate here in a production app.
    }

    // 2. Initialize AppLogger. It can use SocketManager for remote logging if configured.
    if (App.AppLogger && typeof App.AppLogger.initialize === 'function') {
        App.AppLogger.initialize();
        } else {
        console.warn("mainApp.js: App.AppLogger not found or initialize method missing.");
        }

    // 3. Initialize ConfigManager. It depends on SocketManager to fetch the configuration.
    if (App.ConfigManager && typeof App.ConfigManager.init === 'function') {
            App.ConfigManager.init(); 
    } else {
        console.error("mainApp.js: App.ConfigManager not found or init method missing.");
    }

    // 4. Initialize UIManager for tab navigation and general UI structure.
    if (App.UIManager && typeof App.UIManager.init === 'function') {
            App.UIManager.init(); 
    } else {
        console.error("mainApp.js: App.UIManager not found or init method missing.");
    }

    // 5. Initialize view-specific modules.
    // These modules typically populate specific tabs or UI sections and might depend on ConfigManager and UIManager.
    if (App.SettingsView && typeof App.SettingsView.init === 'function') {
            App.SettingsView.init(); 
    } else {
        console.warn("mainApp.js: App.SettingsView not found or init method missing.");
    }
    
    if (App.GlobalStatusView && typeof App.GlobalStatusView.init === 'function') {
        App.GlobalStatusView.init();
    } else {
        console.warn("mainApp.js: App.GlobalStatusView not found or init method missing.");
    }

    if (App.InputMappingView && typeof App.InputMappingView.init === 'function') {
    App.InputMappingView.init();
    } else {
        console.warn("mainApp.js: App.InputMappingView not found or init method missing.");
    }

    if (App.ChannelManager && typeof App.ChannelManager.init === 'function') {
        App.ChannelManager.init();
    } else {
        console.warn("mainApp.js: App.ChannelManager not found or init method missing.");
    }

    if (App.VariableManager && typeof App.VariableManager.init === 'function') {
        App.VariableManager.init();
    } else {
        console.warn("mainApp.js: App.VariableManager not found or init method missing.");
    }

    console.log("App: Module initialization attempted.");

    console.log("App: Initialization complete.");
}); 