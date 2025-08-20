/**
 * SocketManager: Centralizes Socket.IO connection and event dispatch.
 */
window.App = window.App || {};
// const App = window.App;

// Manages Socket.IO connection and events

App.SocketManager = (function() {
    'use strict';

    let socket = null; // Holds the Socket.IO client instance.
    const eventHandlers = {}; // Stores registered handlers for specific Socket.IO events, keyed by event name.
    let isConnectedStatus = false; // Tracks the current connection status.
    const onConnectCallbacks = []; // A queue for callbacks to be executed once the socket connects.
    let managerInstanceId = Date.now() + '.' + Math.random().toString(36).substring(2, 7); // Unique ID for logging, helps distinguish instances if re-initialized.

    /**
     * Initializes the Socket.IO connection and sets up default event listeners.
     * This function is called internally by the public `init` method.
     */
    function initialize() {
        if (socket) {
            console.warn(`SocketManager [${managerInstanceId}]: Initialize called but socket already exists. Re-initializing is not standard. Current SID: ${socket.id}`);
            // Optionally, one might choose to disconnect an existing socket here if re-initialization is a desired feature.
            // socket.disconnect(); 
            // socket = null;
        }

        // Re-generate instance ID in case of re-initialization, though this path should ideally not be hit.
        managerInstanceId = Date.now() + '.' + Math.random().toString(36).substring(2, 7);
        console.log(`SocketManager [${managerInstanceId}]: Initializing new connection...`);

        socket = io(undefined, { // `undefined` connects to the server that served the page.
            reconnectionAttempts: 5, // Number of times to try reconnecting on disconnection.
            reconnectionDelay: 3000, // Delay (ms) between reconnection attempts.
            // timeout: 10000, // Optional: connection timeout in milliseconds.
        });

        /**
         * Universal event listener for all incoming Socket.IO events.
         * It logs non-noisy events and dispatches them to registered handlers.
         * @param {string} eventName - The name of the received event.
         * @param {...any} args - Arguments associated with the event.
         */
        socket.onAny((eventName, ...args) => {
            // Skip noisy events in logs
            const noisyEvents = ['raw_inputs_update', 'channel_value_update', 'variable_value_updated'];
            
            if (!noisyEvents.includes(eventName)) {
                console.log(`SocketManager [${managerInstanceId}] Central Dispatch: Event '${eventName}' received. Dispatching to ${eventHandlers[eventName]?.length || 0} handlers.`, args);
            } else {
                // For noisy events, perhaps a more subdued log or conditional logging could be implemented if needed for debugging.
                // console.debug(`SocketManager [${managerInstanceId}]: Noisy event '${eventName}' received.`);
            }

            // Dispatch to specific registered handlers, excluding built-in connection events handled separately.
            if (eventHandlers[eventName] && eventName !== 'connect' && eventName !== 'disconnect' && eventName !== 'connect_error') {
                eventHandlers[eventName].forEach(handler => {
                    try {
                        handler(...args);
                    } catch (error) {
                        console.error(`SocketManager [${managerInstanceId}]: Error in handler for event '${eventName}':`, error, "Handler details:", handler.toString());
                    }
                });
            }
        });

        /**
         * Handles the 'connect' event from Socket.IO.
         * Sets connection status, processes queued onConnect callbacks, and notifies general 'connect' subscribers.
         */
        socket.on('connect', () => {
            isConnectedStatus = true;
            console.log(`SocketManager [${managerInstanceId}]: Successfully connected. SID: ${socket.id}. Processing ${onConnectCallbacks.length} onConnect callbacks.`);
            processOnConnectedCallbacks(); // Execute any queued callbacks.
            if (eventHandlers['connect']) {
                eventHandlers['connect'].forEach(cb => cb(socket.id));
            }
        });

        /**
         * Handles the 'disconnect' event from Socket.IO.
         * Updates connection status and notifies general 'disconnect' subscribers.
         * @param {string} reason - The reason for disconnection.
         */
        socket.on('disconnect', (reason) => {
            isConnectedStatus = false;
            console.warn(`SocketManager [${managerInstanceId}]: Disconnected. SID: ${socket ? socket.id : 'N/A'}. Reason:`, reason);
            if (eventHandlers['disconnect']) {
                eventHandlers['disconnect'].forEach(cb => cb(reason));
            }
        });

        /**
         * Handles the 'connect_error' event from Socket.IO.
         * Logs the error, updates connection status, and notifies general 'connect_error' subscribers.
         * @param {Error} error - The connection error object.
         */
        socket.on('connect_error', (error) => {
            isConnectedStatus = false;
            console.error(`SocketManager [${managerInstanceId}]: Connection error.`, error);
            if (eventHandlers['connect_error']) {
                eventHandlers['connect_error'].forEach(cb => cb(error));
            }
        });
    }

    /**
     * Processes and executes all callbacks currently in the `onConnectCallbacks` queue.
     * Callbacks are removed from the queue as they are executed.
     */
    function processOnConnectedCallbacks() {
        console.log(`SocketManager [${managerInstanceId}]: Processing ${onConnectCallbacks.length} onConnected callbacks.`);
        while (onConnectCallbacks.length > 0) {
            const callback = onConnectCallbacks.shift(); // Get and remove the first callback.
            try {
                callback();
            } catch (error) {
                console.error(`SocketManager [${managerInstanceId}]: Error executing an onConnected callback:`, error);
            }
            }
    }

    // Public API of the SocketManager module.
    return {
        /**
         * Public initialization point for the SocketManager.
         * Ensures that the `initialize` function (which sets up the socket) is called only once.
         */
        init: function() {
            if (!socket) {
                console.log(`SocketManager [${managerInstanceId}]: Public init() called. Proceeding with initialization.`);
                initialize();
            } else {
                console.warn(`SocketManager [${managerInstanceId}]: Public init() called, but already initialized. SID: ${socket.id}`);
            }
        },
        
        /**
         * Registers a callback function to be executed once the socket is connected.
         * If the socket is already connected, the callback is executed immediately.
         * Otherwise, it's queued.
         * @param {Function} callback - The function to execute upon connection.
         */
        onConnected: function(callback) {
            if (typeof callback !== 'function') {
                console.error(`SocketManager [${managerInstanceId}]: onConnected: Provided argument is not a function.`, callback);
                return;
            }
            if (isConnectedStatus && socket && socket.connected) {
                console.log(`SocketManager [${managerInstanceId}]: Already connected. Executing onConnected callback immediately.`);
                try { 
                    callback(); 
                } catch (e) { 
                    console.error(`SocketManager [${managerInstanceId}]: Error directly executing onConnected callback:`, e);
                }
            } else {
                onConnectCallbacks.push(callback);
                console.log(`SocketManager [${managerInstanceId}]: Queued callback for onConnected. Queue size: ${onConnectCallbacks.length}`);
            }
        },

        /**
         * Emits an event through the Socket.IO connection.
         * Logs an error if the socket is not connected.
         * @param {string} eventName - The name of the event to emit.
         * @param {Object} [data] - The data to send with the event.
         */
        emit: function(eventName, data) {
            if (socket && isConnectedStatus && socket.connected) { // Double-check socket.connected for robustness.
                socket.emit(eventName, data);
            } else {
                console.error(`SocketManager [${managerInstanceId}]: Cannot emit '${eventName}'. Socket not connected or connection status mismatch.`);
            }
        },

        /**
         * Registers an event handler for a specific Socket.IO event.
         * @param {string} eventName - The name of the event to listen for.
         * @param {Function} callback - The function to call when the event is received.
         * @returns {Function} A function that can be called to unregister the event handler.
         */
        on: function(eventName, callback) {
            if (typeof callback !== 'function') {
                console.error(`SocketManager [${managerInstanceId}]: Attempted to register non-function handler for event '${eventName}'.`, callback);
                return () => {}; // Return a no-op unregister function.
            }
            if (!eventHandlers[eventName]) {
                eventHandlers[eventName] = [];
            }
            eventHandlers[eventName].push(callback);
            
            // Return an unregister function.
            return () => {
                if(eventHandlers[eventName]){
                    eventHandlers[eventName] = eventHandlers[eventName].filter(cb => cb !== callback);
                    if (eventHandlers[eventName].length === 0) { 
                        delete eventHandlers[eventName]; 
                    }
                }
            };
        },

        /**
         * Gets the current Socket.IO client ID.
         * @returns {string|null} The socket ID if connected, otherwise null.
         */
        getSocketId: function() {
            return socket ? socket.id : null;
        },

        /**
         * Checks if the socket is currently connected.
         * @returns {boolean} True if connected, false otherwise.
         */
        isConnected: function() {
            return isConnectedStatus && socket && socket.connected; // Provides a robust check of connection state.
        }
    };
})();

// End of module