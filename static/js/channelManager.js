// ChannelManager: Manage OSC channel UI in the 'OSC Channels' tab
window.App = window.App || {};
// const App = window.App;

App.ChannelManager = (function() {
    'use strict';

    // Module-level variables for DOM Elements
    let channelsListArea = null;
    let channelsSortModeSelect = null; // New: sort mode
    let showAddChannelModalButton = null; // Button to trigger the 'Add Channel' modal.

    // 'Add Channel' Modal Elements
    let addChannelModal = null;
    let newChannelNameInput = null;
    let cancelAddChannelBtn = null;
    let newChannelNameError = null;
    let addChannelForm = null;

    // 'Edit Channel' Panel Elements
    let channelEditPanel = null;
    let selectedChannelLabel = null; // Displays the name of the channel being edited.
    let editOscTypeSelect = null;    // Dropdown for OSC data type (float, int, string).
    let editDefaultInput = null;   // Input for the default value of the channel.
    let groupDefaultInput = null;    // Parent group for the default input element.
    let editRangeMinInput = null;    // Input for the minimum range of the channel.
    let editRangeMaxInput = null;    // Input for the maximum range of the channel.
    let groupRangeMin = null;        // Parent group for the minimum range input.
    let groupRangeMax = null;        // Parent group for the maximum range input.
    let editStringValue1 = null;   // Input for the first string value (for 'string' type).
    let editStringValue2 = null;   // Input for the second string value (for 'string' type).
    let groupStringValue1 = null;    // Parent group for the first string value input.
    let groupStringValue2 = null;    // Parent group for the second string value input.
    let editChannelNameInput = null; // Input for channel name (new)
    let editOscAddressInput = null;  // Input for the OSC address.
    let editChannelMappedInputsContainer = null; // Container to list inputs mapped to this channel.
    let editChannelForm = null;      // The form element for editing a channel.
    let cancelChannelEditBtn = null; // Button to cancel editing a channel.

    let _currentChannelsData = {}; // Local cache of channel configurations.
    let _currentChannelRuntimeValues = {}; // Cache for live (runtime) channel values.
    let _currentConfig = null; // Cache for the current configuration
    let _currentEditingChannelName = null; // Cache for the current editing channel name
    let _pendingChannelToEdit = null; // If a channel was just added, open editor after config update

    /**
     * Caches frequently accessed DOM elements for the module.
     * Should be called once during initialization.
     */
    function _cacheDomElements() {
        // Channel List Area
        channelsListArea = document.getElementById('channels-list-area');
        showAddChannelModalButton = document.getElementById('show-add-channel-modal-button');
        channelsSortModeSelect = document.getElementById('channels-sort-mode');

        // 'Add Channel' Modal
        addChannelModal = document.getElementById('addChannelModal');
        newChannelNameInput = document.getElementById('newChannelNameInput');
        cancelAddChannelBtn = document.getElementById('cancelAddChannelBtn');
        newChannelNameError = document.getElementById('newChannelNameError');
        addChannelForm = document.getElementById('addChannelForm');

        // 'Edit Channel' Panel
        channelEditPanel = document.getElementById('channelEditConfig');
        selectedChannelLabel = document.getElementById('selectedChannelLabel');
        editOscTypeSelect = document.getElementById('editOscType');
        editDefaultInput = document.getElementById('editDefault');
        if (editDefaultInput) groupDefaultInput = editDefaultInput.parentElement; 
        
        editRangeMinInput = document.getElementById('editRangeMin');
        editRangeMaxInput = document.getElementById('editRangeMax');
        if (editRangeMinInput) groupRangeMin = editRangeMinInput.parentElement; 
        if (editRangeMaxInput) groupRangeMax = editRangeMaxInput.parentElement; 

        editStringValue1 = document.getElementById('editStringValue1');
        editStringValue2 = document.getElementById('editStringValue2');
        groupStringValue1 = document.getElementById('groupStringValue1');
        groupStringValue2 = document.getElementById('groupStringValue2');

        editChannelNameInput = document.getElementById('editChannelName');
        editOscAddressInput = document.getElementById('editOscAddress');
        editChannelMappedInputsContainer = document.getElementById('editChannelMappedInputsContainer');
        editChannelForm = document.getElementById('editChannelForm');
        cancelChannelEditBtn = document.getElementById('cancelChannelEditBtnInPanel');
    }

    /**
     * Renders the list of OSC channels in the UI.
     * @param {Object} channelsData - An object containing channel configurations, keyed by channel name.
     * @param {Object} fullConfig - The complete application configuration, used to find mapped inputs.
     */
    function _renderChannelList(channelsData, fullConfig) {
        if (!channelsListArea) {
            console.error("ChannelManager: channelsListArea DOM element not found.");
            return;
        }
        channelsListArea.innerHTML = ''; // Clear existing list.
        _currentChannelsData = channelsData || {};

        if (!channelsData || Object.keys(channelsData).length === 0) {
            channelsListArea.innerHTML = '<p class="text-gray-400 italic">No OSC channels defined. Click "Add New Channel" to create one.</p>';
            return;
        }

        // Determine sort mode (defaults to name)
        const sortMode = channelsSortModeSelect && channelsSortModeSelect.value ? channelsSortModeSelect.value : 'name';

        const sortedChannels = App.ChannelUtils.sortChannelEntries(Object.entries(channelsData), sortMode);

        for (const [name, channel] of sortedChannels) {
            let allMappedInputs = [];
            // Aggregate inputs mapped to this channel from all layers.
            if (fullConfig && fullConfig.layers) {
                for (const layerId in fullConfig.layers) {
                    const layer = fullConfig.layers[layerId];
                    if (layer && layer.input_mappings) {
                        const layerSpecificMappedInputs = Object.entries(layer.input_mappings)
                            .filter(([_, mapping]) => {
                                // Check if the mapping targets this OSC channel.
                                if (mapping.target_type !== 'osc_channel') {
                                    return false;
                                }
                                if (Array.isArray(mapping.target_name)) {
                                    return mapping.target_name.includes(name);
                                }
                                return mapping.target_name === name;
                            })
                            .map(([input, mapping]) => {
                                let modeDisplay = mapping.action;
                                // Format display for 'rate' action.
                                if (mapping.action === 'rate') {
                                    const params = mapping.params || {};
                                    let parts = [];
                                    if (input.includes('stick')) { // Example: Check if input is a stick for Invert/Normal display.
                                        parts.push(params.invert ? 'Inverted' : 'Normal');
                                    }
                                    parts.push(`x${params.rate_multiplier !== undefined ? params.rate_multiplier : 1.0}`);
                                    modeDisplay = `rate (${parts.join(', ')})`;
                                } else if (mapping.action === 'reset') {
                                    modeDisplay = 'Reset Channel';
                                }
                                return `Layer ${layerId}: ${input} (${modeDisplay})`;
                            });
                        allMappedInputs = allMappedInputs.concat(layerSpecificMappedInputs);
                    }
                }
            }

            const div = document.createElement('div');
            div.className = 'p-3 border border-gray-700 rounded bg-gray-800 relative overflow-hidden shadow-md';
            div.setAttribute('data-channel', name);

            const fillDiv = document.createElement('div');
            fillDiv.id = `meter-fill-${name}`;
            fillDiv.className = 'channel-item-meter-fill'; // Class for styling the background fill meter.
            div.appendChild(fillDiv);

            // Action buttons (Edit, Delete) for the channel item.
            const buttonsDiv = document.createElement('div');
            buttonsDiv.style.position = 'absolute';
            buttonsDiv.style.top = '0.5rem';
            buttonsDiv.style.right = '0.5rem';
            buttonsDiv.style.zIndex = '20'; // Ensure buttons are above the meter fill.
            buttonsDiv.className = 'space-x-1';
            buttonsDiv.innerHTML = `
                <button class="btn btn-warning btn-xs" data-action="edit-channel" data-channel-name="${name}">Edit</button>
                <button class="btn btn-danger btn-xs" data-action="delete-channel" data-channel-name="${name}">Delete</button>
            `;
            div.appendChild(buttonsDiv);

            const contentWrapper = document.createElement('div');
            contentWrapper.className = 'relative z-10'; // Content above the fill meter.

            // Robustly handle range display.
            let rangeDisplay = "N/A";
            if (channel && channel.range && Array.isArray(channel.range) && channel.range.length === 2) {
                rangeDisplay = `${channel.range[0]} - ${channel.range[1]}`;
            } else if (channel && channel.hasOwnProperty('range_min') && channel.hasOwnProperty('range_max')) {
                // Support old format if present (server should ideally send new format).
                rangeDisplay = `${channel.range_min} - ${channel.range_max}`;
                console.warn(`ChannelManager: Channel '${name}' uses old range format (range_min/range_max). Config should be updated.`);
            } else {
                console.warn(`ChannelManager: Channel '${name}' is missing valid range data.`);
            }

            let defaultValueDisplay = (channel && channel.default !== undefined) ? channel.default : "N/A";
            let oscTypeDisplay = (channel && channel.osc_type) ? channel.osc_type : "float"; // Default to float if not specified.
            let oscAddressDisplay = (channel && channel.osc_address) ? channel.osc_address : "N/A";

            // 3-Column Layout for channel information.
            let threeColumnInfoHTML = `<div class="flex justify-between items-start mb-0.5">`;

            // Column 1: Name & Current Value display.
            threeColumnInfoHTML += `
                <div class="w-1/3 pr-1 space-y-0.5">
                    <h3 class="text-base font-semibold text-gray-100 truncate leading-tight" title="${name}">${name}</h3>
                    <div id="meter-value-${name}" class="channel-current-value-display text-lg font-bold">0.00</div>
                </div>
            `;

            // Column 2: Key Properties (Range, Default, Type).
            threeColumnInfoHTML += `
                <div class="w-1/3 px-1 text-details-sm space-y-0.5">
                    <div class="truncate" title="Range: ${rangeDisplay}">Range: ${rangeDisplay}</div>
                    <div class="truncate" title="Default: ${defaultValueDisplay}">Default: ${defaultValueDisplay}</div>
                    <div class="truncate" title="OSC Type: ${oscTypeDisplay}">Type: ${oscTypeDisplay}</div>
                </div>
            `;

            // Column 3: Mapped Inputs list.
            let mappedInputsColumnHTML = '';
            if (allMappedInputs.length) {
                mappedInputsColumnHTML = `
                    <ul class="mapped-inputs-list text-details-sm space-y-0.5 list-disc list-inside">
                        ${allMappedInputs.map(input => `<li class="truncate" title="${input}">${input}</li>`).join('')}
                    </ul>
                `;
            } else {
                mappedInputsColumnHTML = '<div class="text-details-sm text-gray-500 italic">No inputs mapped.</div>';
            }
            threeColumnInfoHTML += `
                <div class="w-1/3 pl-1 text-details-sm space-y-0.5">
                    ${mappedInputsColumnHTML}
                </div>
            `;

            threeColumnInfoHTML += `</div>`; // End of 3-column flex row.

            // OSC Address line (full width below the 3-column info).
            let oscAddressHTML = `
                <div class="mt-0.5 text-details-sm truncate" title="OSC: ${oscAddressDisplay}">OSC: ${oscAddressDisplay}</div>
            `;
            
            contentWrapper.innerHTML = threeColumnInfoHTML + oscAddressHTML;
            div.appendChild(contentWrapper);
            channelsListArea.appendChild(div);

            // Initialize meter and value display for the new channel item.
            const initialValue = _currentChannelRuntimeValues[name] !== undefined ? _currentChannelRuntimeValues[name] : channel.default;
            _updateChannelMeter(name, initialValue);
        }
    }

    // deriveOnValuePreview moved to App.ChannelUtils
    
    /**
     * Shows the 'Add New Channel' modal dialog.
     * Clears previous input and error messages.
     */
    function _showAddChannelModal() {
        if (!App.ConfigManager.isConfigLoaded()) {
            alert("Configuration not yet loaded. Please wait a moment and try again.");
            return;
        }
        if (addChannelModal) {
            if(newChannelNameInput) newChannelNameInput.value = '';
            if(newChannelNameError) {
                newChannelNameError.style.display = 'none';
                newChannelNameError.textContent = '';
            }
            addChannelModal.classList.remove('hidden');
            if(newChannelNameInput) newChannelNameInput.focus();
        } else {
            console.error("ChannelManager: 'Add Channel' modal DOM element not found!");
        }
    }

    /**
     * Hides the 'Add New Channel' modal dialog.
     */
    function _hideAddChannelModal() {
        if (addChannelModal) {
            addChannelModal.classList.add('hidden');
        }
    }

    /**
     * Handles the confirmation (submission) of the 'Add New Channel' form.
     * Validates the input and emits an event to the backend to add the channel.
     * @param {Event} [event] - The form submission event, optional.
     */
    function _handleConfirmAddChannel(event) {
        if (event) {
            event.preventDefault(); // Prevent default form submission.
            event.stopPropagation();
        }

        if (!newChannelNameInput || !App.ConfigManager.isConfigLoaded()) {
            console.error("ChannelManager: newChannelNameInput is null or config not loaded during add channel attempt.");
            return;
        }

        const channelNameFromInput = newChannelNameInput.value.trim();
        const currentConfig = App.ConfigManager.getConfig();

        // Validate channel name.
        if (channelNameFromInput === "") {
            if(newChannelNameError) {
                newChannelNameError.textContent = "Channel name cannot be empty.";
                newChannelNameError.style.display = 'block';
            }
            return;
        }

        if (currentConfig.internal_channels && currentConfig.internal_channels[channelNameFromInput]) {
            if(newChannelNameError) {
                newChannelNameError.textContent = `Channel "${channelNameFromInput}" already exists.`;
                newChannelNameError.style.display = 'block';
            }
            return;
        }

        if(newChannelNameError) newChannelNameError.style.display = 'none'; // Clear any previous error.

        // Default data for a new channel.
        const channelData = {
            name: channelNameFromInput,
            default: 0,
            range: [0, 1],
            osc_address: `/channel/${channelNameFromInput}`, // Default OSC address pattern.
            osc_type: 'float' // Default OSC type.
        };
        
        // Track desired name to auto-open after config update
        _pendingChannelToEdit = channelNameFromInput;
        App.SocketManager.emit('add_channel', channelData);
        _hideAddChannelModal(); // Hide modal after submission.
    }

    /**
     * Handles the deletion of an OSC channel.
     * Confirms with the user and emits an event to the backend.
     * @param {string} channelName - The name of the channel to delete.
     */
    function _deleteChannel(channelName) {
        if (!App.ConfigManager.isConfigLoaded()) {
            alert("Configuration not loaded. Cannot delete channel.");
            return;
        }
        if (confirm(`Are you sure you want to delete the OSC channel "${channelName}"? This will also remove it from any input mappings.`)) {
            App.SocketManager.emit('delete_channel', { name: channelName });
            // The config update from the server will trigger a re-render of the channel list.
            // If the edit panel was showing this channel, cancel the edit.
            if (channelEditPanel && channelEditPanel.style.display === 'block' && selectedChannelLabel && selectedChannelLabel.textContent === channelName) {
                _cancelChannelEdit();
            }
        }
    }
    
    /**
     * Emits an event to clear a specific input mapping that targets a given channel.
     * Used when unmapping an input from a channel via the channel edit panel.
     * @param {string} layerId - The ID of the layer where the mapping exists.
     * @param {string} inputName - The name of the input whose mapping is to be cleared.
     * @param {string} channelNameToUntarget - The name of the channel being untargeted.
     */
    function _clearSpecificMapping(layerId, inputName, channelNameToUntarget) {
        App.SocketManager.emit('clear_specific_mapping', {
            layer_id: layerId,
            input_name: inputName,
            channel_name: channelNameToUntarget,
            currently_editing_channel: selectedChannelLabel ? selectedChannelLabel.textContent : null // Context for backend.
        });
    }

    /**
     * Updates the visibility and properties of fields in the 'Edit Channel' panel
     * based on the selected OSC data type (e.g., float, int, string).
     * @param {string} oscType - The selected OSC data type.
     */
    function _updateEditPanelForOscType(oscType) {
        const isString = oscType === 'string';
        const isNumeric = oscType === 'float' || oscType === 'int';

        // Toggle visibility of Default input field.
        if (groupDefaultInput) groupDefaultInput.style.display = isNumeric ? '' : 'none';
        else if (editDefaultInput) editDefaultInput.style.display = isNumeric ? '' : 'none';

        // Toggle visibility of numeric Range fields.
        if (groupRangeMin) groupRangeMin.style.display = isNumeric ? '' : 'none';
        else if (editRangeMinInput) editRangeMinInput.style.display = isNumeric ? '' : 'none';

        if (groupRangeMax) groupRangeMax.style.display = isNumeric ? '' : 'none';
        else if (editRangeMaxInput) editRangeMaxInput.style.display = isNumeric ? '' : 'none';

        // Toggle visibility of String-specific value fields.
        if (groupStringValue1) groupStringValue1.style.display = isString ? '' : 'none';
        if (groupStringValue2) groupStringValue2.style.display = isString ? '' : 'none';

        // Adjust properties of the Default input based on type.
        if (editDefaultInput) {
            if (isNumeric) {
                editDefaultInput.type = 'number';
                editDefaultInput.step = (oscType === 'float') ? '0.01' : '1'; // Step for float vs int.
            } else {
                editDefaultInput.type = 'text'; // Though hidden, set to text for string type.
                editDefaultInput.step = ''; 
            }
        }
    }

    /**
     * Populates and displays the 'Edit Channel' panel for a given channel.
     * @param {string} channelName - The name of the channel to edit.
     */
    function _editChannel(channelName, skipTabSwitch = false) {
        const fullConfig = App.ConfigManager.getConfig();
        if (!fullConfig || !fullConfig.internal_channels || !fullConfig.internal_channels[channelName]) {
            alert('Channel data not found. Cannot edit.');
            return;
        }
        const channel = fullConfig.internal_channels[channelName];

        if (!skipTabSwitch && App.UIManager && typeof App.UIManager.showTab === 'function') {
            App.UIManager.showTab('osc-channels-tab'); // Ensure the OSC Channels tab is visible when invoked by user.
        }

        // Visually highlight the channel being edited in the list.
        document.querySelectorAll('#channels-list-area > div.channel-item-editing').forEach(el => {
            el.classList.remove('channel-item-editing');
        });
        const channelItemDiv = document.querySelector(`#channels-list-area div[data-channel="${channelName}"]`);
        if (channelItemDiv) {
            channelItemDiv.classList.add('channel-item-editing');
        }

        // Check if essential edit panel elements are present.
        if (!channelEditPanel || !selectedChannelLabel || !editOscTypeSelect || !editDefaultInput || 
            !editRangeMinInput || !editRangeMaxInput || !editOscAddressInput || 
            !editChannelMappedInputsContainer || !editChannelForm) {
            console.error("ChannelManager: Critical edit panel DOM elements are missing. Check index.html.");
            alert("Critical error: Channel edit panel structure is missing. Please check the HTML.");
            return;
        }
        
        channelEditPanel.style.display = 'block'; // Show the edit panel.
        channelEditPanel.classList.add('sticky-osc-edit-panel'); // Apply sticky positioning.
        
        if (selectedChannelLabel) {
           selectedChannelLabel.textContent = channelName;
           selectedChannelLabel.classList.add('badge-channel-edit-active'); // Style the label for active edit.
        }

        if (editChannelNameInput) editChannelNameInput.value = channelName;
        editOscTypeSelect.value = channel.osc_type || 'float';
        _updateEditPanelForOscType(editOscTypeSelect.value); // Initial UI update based on type.

        // Populate Default value field (only if numeric type).
        if (channel.osc_type !== 'string' && editDefaultInput) {
            editDefaultInput.value = channel.default !== undefined ? channel.default : '';
        } else if (editDefaultInput) {
            editDefaultInput.value = ''; // Clear if string type (field is hidden).
        }
        
        // Populate Range or String values based on OSC type.
        if (channel.osc_type === 'string') {
            if (editStringValue1) editStringValue1.value = (channel.osc_strings && channel.osc_strings[0]) ? channel.osc_strings[0] : '';
            if (editStringValue2) editStringValue2.value = (channel.osc_strings && channel.osc_strings[1]) ? channel.osc_strings[1] : '';
            if (editRangeMinInput) editRangeMinInput.value = ''; // Clear numeric range fields.
            if (editRangeMaxInput) editRangeMaxInput.value = '';
        } else { // Numeric types (float, int).
            if (channel.range && Array.isArray(channel.range) && channel.range.length === 2) {
                if (editRangeMinInput) editRangeMinInput.value = channel.range[0];
                if (editRangeMaxInput) editRangeMaxInput.value = channel.range[1];
            } else if (channel.hasOwnProperty('range_min') && channel.hasOwnProperty('range_max')) { // Support old format.
                if (editRangeMinInput) editRangeMinInput.value = channel.range_min;
                if (editRangeMaxInput) editRangeMaxInput.value = channel.range_max;
            } else { // Fallback if range data is missing/invalid.
                if (editRangeMinInput) editRangeMinInput.value = '';
                if (editRangeMaxInput) editRangeMaxInput.value = '';
            }
            if (editStringValue1) editStringValue1.value = ''; // Clear string value fields.
            if (editStringValue2) editStringValue2.value = '';
        }
        
        editOscAddressInput.value = channel.osc_address || '';
        
        // Populate the list of inputs mapped to this channel.
        editChannelMappedInputsContainer.innerHTML = '';
        let foundMappings = false;
        if (fullConfig.layers) {
            for (const layerId in fullConfig.layers) {
                const layer = fullConfig.layers[layerId];
                if (layer && layer.input_mappings) {
                    Object.entries(layer.input_mappings).forEach(([input, mapping]) => {
                        let targetsChannel = false;
                        if (mapping.target_type === 'osc_channel') { // Check if it's an OSC channel mapping.
                            if (Array.isArray(mapping.target_name)) {
                                targetsChannel = mapping.target_name.includes(channelName);
                            } else {
                                targetsChannel = mapping.target_name === channelName;
                            }
                        }

                        if (targetsChannel) {
                            foundMappings = true;
                            let modeDisplay = mapping.action;
                            // Format 'rate' action display.
                            if (mapping.action === 'rate') {
                                const params = mapping.params || {};
                                let parts = [];
                                if (input.includes('stick')) {
                                    parts.push(params.invert ? 'Inverted' : 'Normal');
                                }
                                parts.push(`x${params.rate_multiplier !== undefined ? params.rate_multiplier : 1.0}`);
                                modeDisplay = `rate (${parts.join(', ')})`;
                            } else if (mapping.action === 'reset') {
                                modeDisplay = 'Reset Channel';
                            }
                            const listItem = document.createElement('div');
                            listItem.className = 'flex justify-between items-center py-0.5';

                            const textSpan = document.createElement('span');
                            textSpan.className = 'text-sm';
                            textSpan.textContent = `Layer ${layerId}: ${input} (${modeDisplay})`;
                            
                            // Button to clear this specific mapping.
                            const clearButton = document.createElement('button');
                            clearButton.type = 'button';
                            clearButton.innerHTML = '&times;'; // 'times' symbol for clear.
                            clearButton.className = 'btn btn-danger btn-xs ml-2 px-1.5 py-0.5';
                            clearButton.title = `Clear this mapping from Layer ${layerId}`;
                            clearButton.onclick = () => {
                                _clearSpecificMapping(layerId, input, channelName);
                                // Optimistically remove just this row from the UI
                                if (listItem && listItem.parentNode) {
                                    listItem.parentNode.removeChild(listItem);
                                }
                            };
                            
                            listItem.appendChild(textSpan);
                            listItem.appendChild(clearButton);
                            editChannelMappedInputsContainer.appendChild(listItem);
                        }
                    });
                }
            }
        }
        if (!foundMappings) {
            editChannelMappedInputsContainer.innerHTML = '<em class="text-sm text-gray-400">No inputs mapped to this channel.</em>';
        }

        // Handle form submission for saving changes.
        editChannelForm.onsubmit = (e) => {
            e.preventDefault(); // Prevent default form submission.
            
            const selectedOscType = editOscTypeSelect.value;
            const updatedChannelData = {
                osc_type: selectedOscType,
                osc_address: editOscAddressInput.value.trim()
            };

            if (selectedOscType === 'string') {
                if (editStringValue1 && editStringValue2) {
                    updatedChannelData.osc_strings = [editStringValue1.value, editStringValue2.value];
                }
                // Remove numeric-specific fields for string type.
                delete updatedChannelData.default;
                delete updatedChannelData.range; 
            } else { // Numeric types (float, int).
                let defaultVal = editDefaultInput ? editDefaultInput.value : '0'; 
                let rangeMinVal = editRangeMinInput ? parseFloat(editRangeMinInput.value) : 0;
                let rangeMaxVal = editRangeMaxInput ? parseFloat(editRangeMaxInput.value) : 1;

                // Ensure defaultVal is parsed as a number for numeric types.
                defaultVal = parseFloat(defaultVal);
                if (isNaN(defaultVal)) defaultVal = 0;


                if (isNaN(rangeMinVal)) rangeMinVal = 0;
                if (isNaN(rangeMaxVal)) rangeMaxVal = (selectedOscType === 'float' ? 1.0 : 127); // Default max based on type.
                
                updatedChannelData.default = defaultVal;
                updatedChannelData.range = [rangeMinVal, rangeMaxVal];
                delete updatedChannelData.osc_strings; // Remove string-specific field.
            }
            const desiredName = (editChannelNameInput ? editChannelNameInput.value.trim() : channelName);
            const wantsRename = desiredName && desiredName !== channelName;

            // First, update channel properties
            App.SocketManager.emit('update_channel', { name: channelName, data: updatedChannelData });

            // Then, if name changed, request rename
            if (wantsRename) {
                App.SocketManager.emit('rename_channel', { old_name: channelName, new_name: desiredName });
            }
        };

        // Attach listener for OSC type change if not already attached.
        if (editOscTypeSelect && !editOscTypeSelect.dataset.listenerAttached) {
            editOscTypeSelect.addEventListener('change', (event) => {
                _updateEditPanelForOscType(event.target.value);
            });
            editOscTypeSelect.dataset.listenerAttached = 'true';
        }

        _currentEditingChannelName = channelName; // Update the cache for the current editing channel
    }

    /**
     * Hides the 'Edit Channel' panel and removes editing-specific UI states.
     */
    function _cancelChannelEdit() {
        if (channelEditPanel) {
            channelEditPanel.style.display = 'none';
            channelEditPanel.classList.remove('sticky-osc-edit-panel');
        }
        
        const currentlyEditingChannelName = selectedChannelLabel ? selectedChannelLabel.textContent : null;
        if (selectedChannelLabel) {
            selectedChannelLabel.classList.remove('badge-channel-edit-active'); // Remove active edit style from label.
        }

        // Remove editing highlight from the channel list item.
        if (currentlyEditingChannelName) {
            const channelItemDiv = document.querySelector(`#channels-list-area div[data-channel="${currentlyEditingChannelName}"]`);
            if (channelItemDiv) {
                channelItemDiv.classList.remove('channel-item-editing');
            }
        }

        _currentEditingChannelName = null; // Clear the cache for the current editing channel
    }

    /**
     * Handles click events within the channels list area, delegating to specific actions
     * like edit or delete based on `data-action` attributes.
     * @param {Event} event - The click event.
     */
    function _handleListAreaClick(event) {
        const target = event.target.closest('button[data-action]'); // Find the closest button with a data-action.
        if (!target) return;

        const action = target.dataset.action;
        const channelName = target.dataset.channelName;

        if (action === 'edit-channel' && channelName) {
            _editChannel(channelName);
        } else if (action === 'delete-channel' && channelName) {
            _deleteChannel(channelName);
        }
    }
    
    /**
     * Initializes the ChannelManager module.
     * Caches DOM elements, sets up event listeners, and subscribes to configuration updates.
     */
    function init() {
        // Initialize ChannelManager and cache DOM elements
        _cacheDomElements();

        if (!channelsListArea) {
            console.error("ChannelManager: CRITICAL - channelsListArea is null. Event listeners and rendering will fail.");
            return; 
        }
        if (!addChannelModal) {
            console.error("ChannelManager: CRITICAL - addChannelModal is null. Modal functionality will be impaired.");
        }

        if (showAddChannelModalButton) {
            showAddChannelModalButton.addEventListener('click', _showAddChannelModal);
        } else {
            console.warn("ChannelManager: 'Show Add Channel Modal' button not found in DOM.");
        }

        if (addChannelForm) {
            addChannelForm.addEventListener('submit', _handleConfirmAddChannel);
        } else {
            console.warn("ChannelManager: 'Add Channel' form not found in DOM.");
        }

        if (channelsSortModeSelect) {
            channelsSortModeSelect.addEventListener('change', () => {
                const cfg = App.ConfigManager.getConfig();
                if (cfg) {
                    _renderChannelList(cfg.internal_channels || {}, cfg);
                }
            });
        }

        if (cancelAddChannelBtn) {
            cancelAddChannelBtn.addEventListener('click', _hideAddChannelModal);
        } else {
            console.warn("ChannelManager: 'Cancel Add Channel' button not found in DOM.");
        }

        channelsListArea.addEventListener('click', _handleListAreaClick);

        // Edit Panel submit is wired in _editChannel; no duplicate listener here
        if (!editChannelForm) {
            console.warn("ChannelManager: 'Edit Channel' form not found in DOM.");
        }

        if (cancelChannelEditBtn) {
            cancelChannelEditBtn.addEventListener('click', _cancelChannelEdit);
        } else {
            console.warn("ChannelManager: 'Cancel Edit Channel' button in panel not found.");
        }

        if (editOscTypeSelect) {
            // Listener is attached in _editChannel to ensure it's only added once.
        } else {
            console.warn("ChannelManager: OSC Type select dropdown in edit panel not found.");
        }
        
        // Subscribe to config updates from ConfigManager to re-render the channel list.
        if (App.ConfigManager) {
            App.ConfigManager.subscribe('configLoaded', _handleConfigUpdate);
            App.ConfigManager.subscribe('configUpdated', _handleConfigUpdate);
        } else {
            console.error("ChannelManager: App.ConfigManager not available for subscription.");
        }

        // Listen for live channel value updates from the backend.
        if (App.SocketManager) {
            App.SocketManager.on('channel_value_update', (data) => {
                if (data && data.name && data.value !== undefined) {
                    _updateChannelMeter(data.name, data.value);
                }
            });
            // Subscribed to 'channel_value_update'
            App.SocketManager.on('channel_operation_status', (status) => {
                try {
                    if (status && status.success && status.operation === 'add' && status.channel_name) {
                        _pendingChannelToEdit = status.channel_name;
                    }
                } catch (e) { /* ignore */ }
            });
        } else {
            console.error("ChannelManager: App.SocketManager not available to subscribe to 'channel_value_update'.");
        }

        // Initialization complete
    }

    /**
     * Public method to refresh the channel list, typically called when the configuration changes
     * or when the OSC Channels tab becomes visible.
     * @param {Object} config - The full application configuration object.
     */
    function refresh(config) {
        if (!config || !config.internal_channels) {
            _renderChannelList({}, config); // Render an empty list if no channels data.
            return;
        }
        _renderChannelList(config.internal_channels, config);
    }

    /**
     * Updates the visual meter (fill percentage) and value display for a specific channel
     * based on its current runtime value.
     * @param {string} channelName - The name of the channel to update.
     * @param {number|string} currentValue - The current runtime value of the channel.
     */
    function _updateChannelMeter(channelName, currentValue) {
        const meterFillDiv = document.getElementById(`meter-fill-${channelName}`);
        const meterValueDiv = document.getElementById(`meter-value-${channelName}`);
        const channelConfig = _currentChannelsData[channelName];

        if (!meterFillDiv || !meterValueDiv || !channelConfig) {
            return; // Silently return if elements or config are not found.
        }

        let displayValue = currentValue;
        let fillPercentage = 0;

        if (channelConfig.osc_type === 'string') {
            fillPercentage = 0; // No visual meter fill for string types.
            const stringList = Array.isArray(channelConfig.osc_strings) ? channelConfig.osc_strings : null;
            // If we have a defined list of strings, map numeric currentValue to a string selection
            if (stringList && stringList.length > 0) {
                let numericVal = NaN;
                if (typeof currentValue === 'number') numericVal = currentValue;
                else if (typeof currentValue === 'string') {
                    const parsed = parseFloat(currentValue);
                    numericVal = isNaN(parsed) ? NaN : parsed;
                }
                if (!isNaN(numericVal)) {
                    const idx = (numericVal >= 0.5 && stringList.length > 1) ? 1 : 0;
                    displayValue = String(stringList[idx]);
                } else {
                    // Fallback to raw string
                    displayValue = typeof currentValue === 'string' ? currentValue : String(currentValue);
                }
            } else {
                // No predefined strings; show raw
                displayValue = typeof currentValue === 'string' ? currentValue : String(currentValue);
            }
            // Truncate long strings for display.
            if (displayValue.length > 15) displayValue = displayValue.substring(0, 12) + "..."; 
        } else { // Numeric types (float, int).
            const minVal = parseFloat(channelConfig.range && channelConfig.range[0] !== undefined ? channelConfig.range[0] : 0);
            const maxVal = parseFloat(channelConfig.range && channelConfig.range[1] !== undefined ? channelConfig.range[1] : 1);
            const numericValue = parseFloat(currentValue);

            if (isNaN(numericValue)) {
                displayValue = "N/A";
                fillPercentage = 0;
            } else {
                if (maxVal > minVal) {
                    fillPercentage = ((numericValue - minVal) / (maxVal - minVal)) * 100;
                } else if (numericValue >= minVal) { 
                    fillPercentage = 100; // If max <= min, fill if value is at or above min.
                } else {
                    fillPercentage = 0;
                }
                fillPercentage = Math.max(0, Math.min(100, fillPercentage)); // Clamp between 0-100%.
                // Format numeric display based on OSC type.
                displayValue = channelConfig.osc_type === 'float' ? numericValue.toFixed(3) : numericValue.toFixed(0);
            }
        }

        meterFillDiv.style.width = `${fillPercentage}%`;
        meterValueDiv.textContent = displayValue;
        _currentChannelRuntimeValues[channelName] = currentValue; // Update runtime value cache.
    }

    /**
     * Handles updates to the global configuration.
     * Re-renders the channel list and, if a channel is being edited, refreshes its edit panel.
     * @param {object} data - The event data from ConfigManager (can be new config or {new, old} object).
     */
    function _handleConfigUpdate(data) {
        const newConfig = App.ConfigManager.getConfig(); // Get the fresh full config
        _currentConfig = newConfig; // Update the module's current config cache

        if (newConfig && newConfig.internal_channels) {
            _renderChannelList(newConfig.internal_channels, newConfig);
        } else {
            _renderChannelList({}, newConfig); // Render empty list if no channels
        }

        // If the edit panel is open for a channel, refresh its content
        if (_currentEditingChannelName) {
            const channelStillExists = newConfig.internal_channels && newConfig.internal_channels[_currentEditingChannelName];
            if (channelStillExists) {
                // Re-populate the edit panel with the updated config
                // The _editChannel function reads from _currentConfig which we just updated
                console.log(`ChannelManager: Config updated. Refreshing edit panel for '${_currentEditingChannelName}'.`);
                // Refresh fields without switching tabs if already editing
                _editChannel(_currentEditingChannelName, true); 
            } else {
                // The channel being edited was deleted, so close the panel
                console.log(`ChannelManager: Config updated. Channel '${_currentEditingChannelName}' no longer exists. Closing edit panel.`);
                _cancelChannelEdit(); // Assumes this function correctly resets state and hides UI
            }
        }

        // Open editor for newly added channel once it exists in config
        if (_pendingChannelToEdit && newConfig && newConfig.internal_channels) {
            if (newConfig.internal_channels[_pendingChannelToEdit]) {
                const nameToEdit = _pendingChannelToEdit;
                _pendingChannelToEdit = null;
                _editChannel(nameToEdit);
            }
        }
    }
    
    // Public API of the ChannelManager module.
    return {
        init: init,
        refresh: refresh,
        cancelEdit: _cancelChannelEdit // Expose method to cancel channel edit externally if needed.
    };

})();

// Note: UIManager should call refresh when OSC tab is shown if needed.