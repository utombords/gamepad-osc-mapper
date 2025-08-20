/**
 * UIManager: Tab navigation and simple coordination with views on tab switch.
 */
window.App = window.App || {};
// const App = window.App;

// Manages overall UI, tab navigation, modals

App.UIManager = (function() {
    'use strict';

    let tabButtons = []; // Array of tab button elements.
    let tabPanes = [];   // Array of tab pane content elements.
    let currentActiveTabId = null; // ID of the currently active tab pane.

    /**
     * Handles click events on tab buttons.
     * Prevents default action and calls `showTab` to switch to the target tab.
     * @param {Event} event - The click event object.
     */
    function _handleTabClick(event) {
        event.preventDefault();
        const tabId = event.currentTarget.dataset.tabTarget;
        if (tabId) {
            showTab(tabId);
        } else {
            console.warn("UIManager: Tab button clicked without a data-tab-target attribute.", event.currentTarget);
        }
    }

    /**
     * Shows the specified tab and hides others.
     * Updates button active states and pane visibility.
     * Notifies relevant managers (ChannelManager, VariableManager, ConfigManager, etc.)
     * to refresh or update their content based on the newly activated tab.
     * @param {string} tabId - The ID of the tab pane to show (e.g., 'osc-channels-tab', 'layer-a-tab').
     */
    function showTab(tabId) {
        if (!tabId || tabId === currentActiveTabId) {
            // Avoid unnecessary processing if the tab is already active or ID is invalid.
            return;
        }

        // Deactivate all tab buttons and hide all tab panes.
        tabButtons.forEach(button => {
            button.classList.remove('active-tab');
        });
        tabPanes.forEach(pane => {
            pane.classList.add('hidden');
            pane.classList.remove('active-pane'); // Ensure only one pane is marked active if styles depend on it.
        });

        const newActiveTabButton = document.querySelector(`.tab-btn[data-tab-target="${tabId}"]`);
        const newActivePane = document.getElementById(tabId);

        if (newActiveTabButton) {
            newActiveTabButton.classList.add('active-tab');
        } else {
            console.warn(`UIManager: Could not find tab button for target ID: ${tabId}`);
        }

        if (newActivePane) {
            newActivePane.classList.remove('hidden');
            newActivePane.classList.add('active-pane');
        } else {
            console.warn(`UIManager: Could not find tab pane for ID: ${tabId}`);
            // If the pane doesn't exist, we probably shouldn't set currentActiveTabId to it.
            // However, the rest of the logic might still try to update managers based on this ID.
            // For now, let it proceed, but this indicates a potential configuration issue.
        }

        currentActiveTabId = tabId;
        console.log(`UIManager: Switched to tab: ${tabId}`);

        // Notify relevant managers to refresh or update their content.
        const currentConfig = App.ConfigManager ? App.ConfigManager.getConfig() : null;

        switch (tabId) {
            case 'osc-channels-tab':
                if (App.ChannelManager && typeof App.ChannelManager.refresh === 'function') {
                    App.ChannelManager.refresh(currentConfig);
                    // If an edit panel for a channel was open, it should remain open.
                    // Switching *away* from this tab could trigger `ChannelManager.cancelEdit()` if desired.
                } else {
                    console.warn('UIManager: App.ChannelManager.refresh not available or App.ConfigManager not ready.');
                }
                break;
            case 'variables-tab':
                if (App.VariableManager && typeof App.VariableManager.refresh === 'function') {
                    App.VariableManager.refresh(currentConfig);
                } else {
                    console.warn('UIManager: App.VariableManager.refresh not available or App.ConfigManager not ready.');
                }
                break;
            case 'settings-tab':
                if (App.SettingsView && typeof App.SettingsView.refresh === 'function') {
                    // SettingsView.refresh might not be strictly necessary if it primarily loads static data on init
                    // or updates reactively. However, calling it can ensure consistency if its data can change.
                    // App.SettingsView.refresh(); // Currently, SettingsView populates on init and via ConfigManager events.
                }
                break;
            default:
                if (tabId.startsWith('layer-')) {
                    // Layer tab IDs are expected to be 'layer-a-tab', 'layer-b-tab', etc.
                    // Extract the layer ID (A, B, C, D).
                    const layerId = tabId.substring(6, 7).toUpperCase(); // e.g., 'A' from 'layer-a-tab'.
                    if (App.ConfigManager && typeof App.ConfigManager.setActiveUiLayerId === 'function') {
                        App.ConfigManager.setActiveUiLayerId(layerId);
                        // InputMappingView reacts to 'activeUiLayerChanged' event from ConfigManager.
                    } else {
                        console.warn("UIManager: App.ConfigManager.setActiveUiLayerId not available.");
                    }
                }
                break;
        }
    }

    // Public API of the UIManager module.
    return {
        /**
         * Initializes the UIManager.
         * Caches tab buttons and panes, sets up click listeners for tab navigation,
         * and activates the initial tab (either the first one or one marked with 'active-tab').
         * Also subscribes to ConfigManager's 'activeUiLayerChanged' event to sync layer tabs.
         */
        init: function() {
            console.log("UIManager: Initializing...");
            tabButtons = Array.from(document.querySelectorAll('#tabs-navigation .tab-btn'));
            tabPanes = Array.from(document.querySelectorAll('#tab-content-area .tab-pane'));

            if (tabButtons.length === 0 || tabPanes.length === 0) {
                console.warn("UIManager: No tab buttons or panes found. Tab functionality will be impaired.");
                // Do not return early, as other initializations like ConfigManager subscription might still be useful.
            }

            tabButtons.forEach(button => {
                button.addEventListener('click', _handleTabClick);
            });

            // Determine and activate the initial tab.
            let initiallyActiveButton = tabButtons.find(btn => btn.classList.contains('active-tab'));
            if (!initiallyActiveButton && tabButtons.length > 0) {
                initiallyActiveButton = tabButtons[0]; // Default to the first tab button.
            }

            if (initiallyActiveButton) {
                // Simulate a click to ensure all associated logic (like notifying ConfigManager) runs.
                initiallyActiveButton.click(); 
                console.log(`UIManager: Initial active tab set to: ${initiallyActiveButton.dataset.tabTarget || 'first button'} via simulated click.`);
            } else if (tabButtons.length > 0) {
                 console.warn("UIManager: Could not determine an initial active tab, though tab buttons exist.");
            } else {
                console.log("UIManager: No tab buttons found to set an initial active tab.");
            }
            
            // Listen to ConfigManager for programmatic changes to the active UI layer.
            // This ensures tab UI stays in sync if layer changes originate outside direct tab clicks.
            if (App.ConfigManager && typeof App.ConfigManager.subscribe === 'function') {
                App.ConfigManager.subscribe('activeUiLayerChanged', (newLayerId) => {
                    const targetTabId = `layer-${newLayerId.toLowerCase()}-tab`; // Construct tab ID, e.g., 'layer-a-tab'.
                    if (currentActiveTabId !== targetTabId) {
                        const targetButton = tabButtons.find(btn => btn.dataset.tabTarget === targetTabId);
                        if (targetButton) {
                            console.log(`UIManager: 'activeUiLayerChanged' event for layer ${newLayerId}. Simulating click on tab ${targetTabId} to sync UI.`);
                            targetButton.click(); // Simulate click to switch tab and run associated logic.
                        } else {
                            console.warn(`UIManager: Received 'activeUiLayerChanged' for layer ${newLayerId}, but could not find corresponding tab button for ${targetTabId}.`);
                        }
                    }
                });
            } else {
                console.warn("UIManager: ConfigManager not available for subscribing to 'activeUiLayerChanged' events.");
            }

            console.log("UIManager: Initialization complete.");
        },

        /**
         * Public method to switch to a specific tab.
         * @param {string} tabId - The ID of the tab pane to show.
         */
        showTab: showTab,

        /**
         * Gets the ID of the currently active tab.
         * @returns {string|null} The ID of the active tab pane, or null if none is active.
         */
        getActiveTabId: function() {
            return currentActiveTabId;
        }
    };
})(); 