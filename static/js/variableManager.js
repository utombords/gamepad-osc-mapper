/**
 * VariableManager: Manage internal variables UI (list, add/edit/delete, OSC on change).
 */
window.App = window.App || {};
// const App = window.App; // Can be used if preferred, but window.App works directly.

App.VariableManager = (function() {
    'use strict';

    // Module-level variables for DOM Elements.
    let variablesListArea = null; // Area to display the list of variables.
    let showAddVariableModalButton = null; // Button to trigger the 'Add Variable' modal.

    // 'Add Variable' Modal Elements.
    let addVariableModal = null;
    let newVariableNameInput = null;
    let confirmAddVariableBtn = null;
    let cancelAddVariableBtn = null;
    let newVariableNameError = null;
    let addVariableForm = null;

    // 'Edit Variable' Panel Elements.
    let variableEditPanel = null; // The main panel for editing a variable.
    let selectedVariableLabelElement = null; // Displays the name of the variable being edited.
    let editVariableInitialValueInput = null;
    let editVariableMinValueInput = null;
    let editVariableMaxValueInput = null;
    let editVariableForm = null; // The form within the edit panel.
    let cancelVariableEditBtn = null; // Button to cancel editing in the panel.
    let editVariableMappedInputsContainer = null; // Container to list inputs mapped to this variable.

    // OSC on Change configuration elements within the 'Edit Variable' Panel.
    let editVariableSendOscOnChangeCheckbox = null;
    let editVariableOscConfigGroup = null; // The group of OSC config fields, shown/hidden by the checkbox.
    let editVariableOscAddressInput = null;
    let editVariableOscValueTypeSelect = null;
    let editVariableOscValueContentInput = null; // e.g., 'value', 'normalized_value', or a specific string/number.

    let _currentVariablesData = {}; // Local cache of variable configurations and their current states.
    let _currentEditingVariableName = null; // Tracks which variable is open in the edit panel

    /**
     * Caches frequently accessed DOM elements for the module.
     * Should be called once during initialization.
     */
    function _cacheDomElements() {
        variablesListArea = document.getElementById('variables-list-area');
        showAddVariableModalButton = document.getElementById('show-add-variable-modal-button');

        // Add Variable Modal elements
        addVariableModal = document.getElementById('addVariableModal');
        newVariableNameInput = document.getElementById('newVariableNameInput');
        confirmAddVariableBtn = document.getElementById('confirmAddVariableBtn');
        cancelAddVariableBtn = document.getElementById('cancelAddVariableBtn');
        newVariableNameError = document.getElementById('newVariableNameError');
        addVariableForm = document.getElementById('addVariableForm');

        // Edit Variable Panel elements
        variableEditPanel = document.getElementById('variableEditConfig'); 
        selectedVariableLabelElement = document.getElementById('selectedVariableLabel');
        editVariableInitialValueInput = document.getElementById('editVariableInitialValue');
        editVariableMinValueInput = document.getElementById('editVariableMinValue');
        editVariableMaxValueInput = document.getElementById('editVariableMaxValue');
        editVariableForm = document.getElementById('editVariableForm');
        editVariableMappedInputsContainer = document.getElementById('editVariableMappedInputsContainer');
        // cancelVariableEditBtn is specifically looked up in init() as its ID might be more specific (e.g., #cancelVariableEditBtnInPanel)

        // OSC on Change DOM elements (in Edit Panel)
        editVariableSendOscOnChangeCheckbox = document.getElementById('editVariableSendOscOnChange');
        editVariableOscConfigGroup = document.getElementById('editVariableOscConfigGroup');
        editVariableOscAddressInput = document.getElementById('editVariableOscAddress');
        editVariableOscValueTypeSelect = document.getElementById('editVariableOscValueType');
        editVariableOscValueContentInput = document.getElementById('editVariableOscValueContent');
    }

    /**
     * Renders the list of internal variables in the UI.
     * @param {Object} variablesData - An object containing variable configurations, keyed by variable name.
     * @param {Object} fullConfig - The complete application configuration, used to find mapped inputs.
     */
    function _renderVariableList(variablesData, fullConfig) {
        if (!variablesListArea) {
            console.error("VariableManager: variablesListArea DOM element not found. Cannot render list.");
            return;
        }
        variablesListArea.innerHTML = ''; // Clear existing list.
        _currentVariablesData = variablesData || {}; // Update local cache.

        if (!variablesData || Object.keys(variablesData).length === 0) {
            variablesListArea.innerHTML = '<p class="text-gray-400 italic">No internal variables defined. Click "Add New Variable" to create one.</p>';
            return;
        }

        // Sort variables alphabetically by name for consistent display.
        const sortedVariables = Object.entries(variablesData).sort(([nameA], [nameB]) => nameA.localeCompare(nameB));

        for (const [name, variable] of sortedVariables) {
            let allMappedInputs = [];
            // Aggregate inputs mapped to this variable from all layers.
            if (fullConfig && fullConfig.layers) {
                for (const layerId in fullConfig.layers) {
                    const layer = fullConfig.layers[layerId];
                    if (layer && layer.input_mappings) {
                        const layerSpecificMappedInputs = Object.entries(layer.input_mappings)
                            .filter(([/*inputName*/, mapping]) => {
                                // Check direct variable actions.
                                if ((mapping.action === 'set_variable' || mapping.action === 'toggle_variable') && mapping.target_variable === name) {
                                    return true;
                                }
                                // Check actions targeting 'internal_variable' by name.
                                if ((mapping.action === 'increment' || mapping.action === 'decrement' || mapping.action === 'set_value_from_input' || mapping.action === 'step_by_multiplier_on_trigger') &&
                                    mapping.target_type === 'internal_variable' && mapping.target_name === name) {
                                    return true;
                                }
                                return false;
                            })
                            .map(([input, mapping]) => {
                                let actionDisplay = '';
                                if (mapping.action === 'set_variable') {
                                    actionDisplay = `Set to ${mapping.params.target_value}`;
                                } else if (mapping.action === 'toggle_variable') {
                                    actionDisplay = 'Toggle';
                                } else if (mapping.action === 'increment') {
                                    actionDisplay = 'Increment';
                                } else if (mapping.action === 'decrement') {
                                    actionDisplay = 'Decrement';
                                } else if (mapping.action === 'set_value_from_input') {
                                    actionDisplay = 'Set from Input';
                                } else if (mapping.action === 'step_by_multiplier_on_trigger') {
                                    actionDisplay = 'Step by Multiplier';
                                } else {
                                    actionDisplay = mapping.action; // Fallback for other actions.
                                }
                                return `Layer ${layerId}: ${input} (${actionDisplay})`;
                            });
                        allMappedInputs = allMappedInputs.concat(layerSpecificMappedInputs);
                    }
                }
            }

            const div = document.createElement('div');
            div.className = 'p-3 border border-gray-700 rounded bg-gray-800 shadow-sm flex justify-between items-center';
            div.setAttribute('data-variable', name);

            const infoDiv = document.createElement('div');
            infoDiv.className = 'flex-grow';
            
            const primaryInfoLine = document.createElement('div');
            primaryInfoLine.className = 'flex items-baseline space-x-3';

            const nameSpan = document.createElement('span');
            nameSpan.className = 'text-gray-100 font-semibold';
            nameSpan.textContent = name;
            primaryInfoLine.appendChild(nameSpan);

            const valueSpan = document.createElement('span');
            valueSpan.id = `variable-value-${name}`; // For live updates.
            valueSpan.className = 'text-sm text-gray-400';
            
            let displayParts = [];
            const currentValue = variable.current_value === undefined ? variable.initial_value : variable.current_value;
            displayParts.push(`Current: ${currentValue}`);
            if (variable.min_value !== undefined && variable.min_value !== null) {
                displayParts.push(`Min: ${variable.min_value}`);
            }
            if (variable.max_value !== undefined && variable.max_value !== null) {
                displayParts.push(`Max: ${variable.max_value}`);
            }
            valueSpan.textContent = `(${displayParts.join(', ')})`;
            primaryInfoLine.appendChild(valueSpan);

            if (variable.on_change_osc && variable.on_change_osc.enabled) {
                const oscInfoSpan = document.createElement('span');
                oscInfoSpan.className = 'text-xs text-blue-400';
                let oscInfoText = `OSC: ${variable.on_change_osc.address || "(no address)"}`;
                if (variable.on_change_osc.value_content && variable.on_change_osc.value_content !== 'value') { // Show if not default 'value'
                    oscInfoText += ` -> ${variable.on_change_osc.value_content}`;
                }
                 if (variable.on_change_osc.value_type) {
                    oscInfoText += ` (${variable.on_change_osc.value_type})`;
                }
                oscInfoSpan.textContent = oscInfoText;
                oscInfoSpan.title = `Sends OSC to ${variable.on_change_osc.address} when value changes. Type: ${variable.on_change_osc.value_type}. Content: ${variable.on_change_osc.value_content}.`;
                primaryInfoLine.appendChild(oscInfoSpan);
            }
            infoDiv.appendChild(primaryInfoLine);

            if(allMappedInputs.length > 0) {
                const mappedInputsLabel = document.createElement('div');
                mappedInputsLabel.className = 'text-xs text-gray-500 mt-1';
                mappedInputsLabel.textContent = 'Used by: ' + allMappedInputs.join(', ');
                mappedInputsLabel.title = 'Inputs mapped to this variable: \n' + allMappedInputs.join('\n');
                infoDiv.appendChild(mappedInputsLabel);
            }

            const buttonsDiv = document.createElement('div');
            buttonsDiv.className = 'space-x-1';
            buttonsDiv.innerHTML = `
                <button class="btn btn-warning btn-xs" data-action="edit-variable" data-variable-name="${name}" title="Edit ${name}">Edit</button>
                <button class="btn btn-danger btn-xs" data-action="delete-variable" data-variable-name="${name}" title="Delete ${name}">Delete</button>
            `;

            div.appendChild(infoDiv);
            div.appendChild(buttonsDiv);
            variablesListArea.appendChild(div);
        }
    }

    /**
     * Shows the 'Add New Variable' modal dialog.
     * Clears previous input and error messages.
     */
    function _showAddVariableModal() {
        if (!App.ConfigManager || !App.ConfigManager.isConfigLoaded()) {
            alert("Configuration not yet loaded. Please wait a moment and try again.");
            return;
        }
        if (addVariableModal) {
            if(newVariableNameInput) newVariableNameInput.value = '';
            if(newVariableNameError) {
                newVariableNameError.style.display = 'none';
                newVariableNameError.textContent = '';
            }
            addVariableModal.classList.remove('hidden');
            if(newVariableNameInput) newVariableNameInput.focus();
        } else {
            console.error("VariableManager: 'Add Variable' modal DOM element not found.");
        }
    }

    /**
     * Hides the 'Add New Variable' modal dialog.
     */
    function _hideAddVariableModal() {
        if (addVariableModal) {
            addVariableModal.classList.add('hidden');
        }
    }

    /**
     * Handles the confirmation (submission) of the 'Add New Variable' form.
     * Validates the input and emits an event to the backend to add the variable.
     * @param {Event} [event] - The form submission event, optional (to prevent default if called from form submit).
     */
    function _handleConfirmAddVariable(event) {
        if (event) {
            event.preventDefault(); // Prevent default form submission if applicable.
            event.stopPropagation();
        }
        if (!newVariableNameInput || !App.ConfigManager || !App.ConfigManager.isConfigLoaded()) {
            console.error("VariableManager: newVariableNameInput is null or ConfigManager not ready during add variable attempt.");
            return;
        }

        const variableNameFromInput = newVariableNameInput.value.trim();
        const currentConfig = App.ConfigManager.getConfig();

        if (variableNameFromInput === "") {
            if(newVariableNameError) {
                newVariableNameError.textContent = "Variable name cannot be empty.";
                newVariableNameError.style.display = 'block';
            }
            return;
        }

        if (currentConfig.internal_variables && currentConfig.internal_variables[variableNameFromInput]) {
            if(newVariableNameError) {
                newVariableNameError.textContent = `Variable "${variableNameFromInput}" already exists.`;
                newVariableNameError.style.display = 'block';
            }
            return;
        }

        if(newVariableNameError) newVariableNameError.style.display = 'none'; // Clear any previous error.

        // Default data for a new variable.
        const variableData = {
            name: variableNameFromInput,
            initial_value: 0,
            min_value: undefined,
            max_value: undefined,
            step_value: undefined, // Default step could be 1 or handled by backend.
            // on_change_osc structure is usually added by the backend or when edited.
        };
        
        App.SocketManager.emit('add_variable', variableData);
        _hideAddVariableModal(); // Hide modal after submission.
    }

    /**
     * Handles the deletion of an internal variable.
     * Confirms with the user and emits an event to the backend.
     * @param {string} variableName - The name of the variable to delete.
     */
    function _deleteVariable(variableName) {
        if (!App.ConfigManager || !App.ConfigManager.isConfigLoaded()) {
            alert("Configuration not loaded. Cannot delete variable.");
            return;
        }
        if (confirm(`Are you sure you want to delete the internal variable "${variableName}"? This will also remove it from any input mappings that use it.`)) {
            App.SocketManager.emit('delete_variable', { name: variableName });
            // If the edit panel was showing this variable, cancel the edit.
            if (variableEditPanel && variableEditPanel.style.display === 'block' && selectedVariableLabelElement && selectedVariableLabelElement.textContent === variableName) {
                _cancelVariableEdit();
            }
        }
    }

    /**
     * Populates and displays the 'Edit Variable' panel for a given variable.
     * @param {string} variableName - The name of the variable to edit.
     */
    function _editVariable(variableName) {
        const fullConfig = App.ConfigManager.getConfig();
        if (!fullConfig || !fullConfig.internal_variables || !fullConfig.internal_variables[variableName]) {
            alert('Variable data not found. Cannot edit.');
            return;
        }
        const variable = fullConfig.internal_variables[variableName];

        App.UIManager.showTab('variables-tab'); // Ensure the Variables tab is visible.

        _currentEditingVariableName = variableName; // Remember which variable is being edited

        // Visually highlight the variable being edited in the list.
        document.querySelectorAll('#variables-list-area > div.variable-item-editing').forEach(el => {
            el.classList.remove('variable-item-editing');
        });
        const variableItemDiv = document.querySelector(`#variables-list-area div[data-variable="${variableName}"]`);
        if (variableItemDiv) {
            variableItemDiv.classList.add('variable-item-editing');
        }

        // Check if essential edit panel elements are present.
        if (!variableEditPanel || !selectedVariableLabelElement || !editVariableInitialValueInput || !editVariableForm || !editVariableMappedInputsContainer) {
            console.error("VariableManager: Critical edit panel DOM elements are missing. Check index.html and _cacheDomElements.");
            alert("Critical error: Variable edit panel structure is incomplete. Please check the HTML.");
            return;
        }
        
        variableEditPanel.style.display = 'block'; // Show the edit panel.
        if (selectedVariableLabelElement) selectedVariableLabelElement.textContent = variableName;
        editVariableInitialValueInput.value = variable.initial_value;
        editVariableMinValueInput.value = variable.min_value !== undefined ? variable.min_value : '';
        editVariableMaxValueInput.value = variable.max_value !== undefined ? variable.max_value : '';

        // Populate OSC on Change fields.
        const oscConfig = variable.on_change_osc || {}; // Default to empty object if not present.
        if (editVariableSendOscOnChangeCheckbox) {
            editVariableSendOscOnChangeCheckbox.checked = oscConfig.enabled || false;
            _toggleOscConfigGroupVisibility(editVariableSendOscOnChangeCheckbox.checked);
        }
        if (editVariableOscAddressInput) editVariableOscAddressInput.value = oscConfig.address || '';
        if (editVariableOscValueTypeSelect) editVariableOscValueTypeSelect.value = oscConfig.value_type || 'float';
        if (editVariableOscValueContentInput) editVariableOscValueContentInput.value = oscConfig.value_content || 'value';

        // Populate the list of inputs mapped to this variable.
        editVariableMappedInputsContainer.innerHTML = '';
        let foundMappings = false;
        if (fullConfig.layers) {
            for (const layerId in fullConfig.layers) {
                const layer = fullConfig.layers[layerId];
                if (layer && layer.input_mappings) {
                    Object.entries(layer.input_mappings).forEach(([input, mapping]) => {
                        let isMatch = false;
                        if (mapping.target_type === 'variable' && 
                            (mapping.action === 'set_variable' || mapping.action === 'toggle_variable') && 
                            mapping.target_variable === variableName) {
                            isMatch = true;
                        }
                        else if (mapping.target_type === 'internal_variable' && 
                                 (mapping.action === 'increment' || mapping.action === 'decrement' || mapping.action === 'set_value_from_input' || mapping.action === 'step_by_multiplier_on_trigger') && 
                                 mapping.target_name === variableName) {
                            isMatch = true;
                        }

                        if (isMatch) {
                            foundMappings = true;
                            let actionDisplay = '';
                            if (mapping.action === 'set_variable') {
                                actionDisplay = `Set to ${mapping.params.target_value}`;
                            } else if (mapping.action === 'toggle_variable') {
                                actionDisplay = 'Toggle';
                            } else if (mapping.action === 'increment') {
                                actionDisplay = 'Increment';
                            } else if (mapping.action === 'decrement') {
                                actionDisplay = 'Decrement';
                            } else if (mapping.action === 'set_value_from_input') {
                                actionDisplay = 'Set from Input';
                            } else if (mapping.action === 'step_by_multiplier_on_trigger') {
                                actionDisplay = 'Step by Multiplier';
                            } else {
                                actionDisplay = mapping.action;
                            }
                            const listItem = document.createElement('div');
                            listItem.className = 'flex justify-between items-center py-0.5';

                            const textSpan = document.createElement('span');
                            textSpan.className = 'text-sm';
                            textSpan.textContent = `Layer ${layerId}: ${input} (${actionDisplay})`;

                            const clearButton = document.createElement('button');
                            clearButton.type = 'button';
                            clearButton.innerHTML = '&times;';
                            clearButton.className = 'btn btn-danger btn-xs ml-2 px-1.5 py-0.5';
                            clearButton.title = `Clear this mapping from Layer ${layerId}`;
                            clearButton.onclick = () => {
                                _clearVariableSpecificMapping(layerId, input);
                                // Optimistically remove only this row from the UI
                                if (listItem && listItem.parentNode) {
                                    listItem.parentNode.removeChild(listItem);
                                }
                            };

                            listItem.appendChild(textSpan);
                            listItem.appendChild(clearButton);
                            editVariableMappedInputsContainer.appendChild(listItem);
                        }
                    });
                }
            }
        }
        if (!foundMappings) {
            editVariableMappedInputsContainer.innerHTML = '<em class="text-sm text-gray-400">Not used by any input mappings.</em>';
        }
        // The form submit listener is attached in init() and persists.
    }

    /**
     * Clears a specific input mapping that targets this variable by removing the mapping for that input on the given layer.
     * Uses the existing clear_input_mapping backend event (removes the entire mapping for that input on that layer).
     * @param {string} layerId
     * @param {string} inputName
     */
    function _clearVariableSpecificMapping(layerId, inputName) {
        if (!App.SocketManager) {
            console.error('VariableManager: SocketManager not available to clear mapping.');
            return;
        }
        App.SocketManager.emit('clear_input_mapping', {
            layer_id: layerId,
            input_name: inputName,
            save_to_all_layers: false
        });
    }

    /**
     * Handles the submission of the 'Edit Variable' form.
     * Gathers data, validates it, and emits an 'update_variable' event to the server.
     * @param {Event} event - The form submission event.
     */
    function _handleSaveVariable(event) {
        event.preventDefault(); // Prevent default form submission.
        const variableName = selectedVariableLabelElement ? selectedVariableLabelElement.textContent : null;
        if (!variableName) {
            alert("Error: No variable selected for saving. Cannot save.");
            return;
        }

        const initialValue = editVariableInitialValueInput ? parseFloat(editVariableInitialValueInput.value) : 0;
        const minValueText = editVariableMinValueInput ? editVariableMinValueInput.value.trim() : '';
        const maxValueText = editVariableMaxValueInput ? editVariableMaxValueInput.value.trim() : '';
        
        const minValue = minValueText !== '' ? parseFloat(minValueText) : undefined;
        const maxValue = maxValueText !== '' ? parseFloat(maxValueText) : undefined;

        if (isNaN(initialValue)) {
            alert("Initial value must be a valid number.");
            editVariableInitialValueInput.focus();
            return;
        }
        if (minValueText !== '' && isNaN(minValue)) {
            alert("Min value must be a valid number or empty.");
            editVariableMinValueInput.focus();
            return;
        }
        if (maxValueText !== '' && isNaN(maxValue)) {
            alert("Max value must be a valid number or empty.");
            editVariableMaxValueInput.focus();
            return;
        }

        if (minValue !== undefined && maxValue !== undefined && minValue >= maxValue) {
            alert("Min Value must be less than Max Value if both are specified.");
            editVariableMinValueInput.focus();
            return;
        }

        const variableData = {
            initial_value: initialValue,
            min_value: minValue,
            max_value: maxValue,
            // step_value is not currently in the edit form, backend will preserve or default it.
            on_change_osc: {
                enabled: editVariableSendOscOnChangeCheckbox ? editVariableSendOscOnChangeCheckbox.checked : false,
                address: editVariableOscAddressInput ? editVariableOscAddressInput.value.trim() : '',
                value_type: editVariableOscValueTypeSelect ? editVariableOscValueTypeSelect.value : 'float',
                value_content: editVariableOscValueContentInput ? editVariableOscValueContentInput.value.trim() : 'value'
            }
        };

        if (variableData.on_change_osc.enabled && !variableData.on_change_osc.address) {
            alert("OSC Address is required if 'Send OSC on Change' is enabled.");
            if (editVariableOscAddressInput) editVariableOscAddressInput.focus();
            return;
        }

        App.SocketManager.emit('update_variable', { name: variableName, data: variableData });
        
        // Visually close the edit panel; list will refresh upon 'configUpdated' event.
        if (variableEditPanel) variableEditPanel.style.display = 'none';
        const currentlyEditingName = selectedVariableLabelElement ? selectedVariableLabelElement.textContent : null;
        if (currentlyEditingName) {
             const variableItemDiv = document.querySelector(`#variables-list-area div[data-variable="${currentlyEditingName}"]`);
            if (variableItemDiv) {
                variableItemDiv.classList.remove('variable-item-editing');
            }
        }
    }

    /**
     * Hides the 'Edit Variable' panel and removes editing-specific UI states.
     */
    function _cancelVariableEdit() {
        if (variableEditPanel) variableEditPanel.style.display = 'none';
        
        const currentlyEditingName = selectedVariableLabelElement ? selectedVariableLabelElement.textContent : null;
        if (currentlyEditingName) {
             const variableItemDiv = document.querySelector(`#variables-list-area div[data-variable="${currentlyEditingName}"]`);
            if (variableItemDiv) {
                variableItemDiv.classList.remove('variable-item-editing');
            }
        }
        _currentEditingVariableName = null; // Clear current editing state
        // The submit listener is managed by init() and _editVariable setting selectedVariableLabelElement.textContent.
        // No need to re-attach/remove listeners here for the form itself.
    }

    /**
     * Handles click events within the variables list area, delegating to specific actions
     * like edit or delete based on `data-action` attributes.
     * @param {Event} event - The click event.
     */
    function _handleListAreaClick(event) {
        const target = event.target.closest('button[data-action]'); // Find the closest button with a data-action.
        if (!target) return;

        const action = target.dataset.action;
        const variableName = target.dataset.variableName;

        if (action === 'edit-variable' && variableName) {
            _editVariable(variableName);
        } else if (action === 'delete-variable' && variableName) {
            _deleteVariable(variableName);
        }
    }

    /**
     * Toggles the visibility of the OSC configuration group in the edit panel.
     * @param {boolean} isVisible - True to show the group, false to hide it.
     */
    function _toggleOscConfigGroupVisibility(isVisible) {
        if (editVariableOscConfigGroup) {
            if (isVisible) {
                editVariableOscConfigGroup.classList.remove('hidden');
            } else {
                editVariableOscConfigGroup.classList.add('hidden');
            }
        }
    }

    /**
     * Initializes the VariableManager module.
     * Caches DOM elements, sets up event listeners for modals and list interactions,
     * and subscribes to relevant events from ConfigManager and SocketManager.
     */
    function init() {
        console.log("VariableManager: Initializing...");
        _cacheDomElements();

        if (showAddVariableModalButton) {
            showAddVariableModalButton.addEventListener('click', _showAddVariableModal);
        } else {
            console.warn("VariableManager: 'Show Add Variable Modal' button not found in DOM.");
        }
        
        if (addVariableForm) {
            addVariableForm.addEventListener('submit', _handleConfirmAddVariable);
        } else {
            console.warn("VariableManager: 'Add variable' form not found in DOM.");
        }

        if (cancelAddVariableBtn) {
            cancelAddVariableBtn.addEventListener('click', _hideAddVariableModal);
        } else {
            console.warn("VariableManager: 'Cancel Add Variable' button in modal not found.");
        }

        if (variablesListArea) {
            variablesListArea.addEventListener('click', _handleListAreaClick);
        } else {
            console.warn("VariableManager: Variables list area (variables-list-area) not found in DOM.");
        }

        // Edit Panel specific listeners
        if (editVariableForm) {
            // Clear any potentially old onsubmit handlers and attach the new one.
            editVariableForm.onsubmit = null; 
            editVariableForm.addEventListener('submit', _handleSaveVariable);
        } else {
             console.warn("VariableManager: 'Edit variable' form (editVariableForm) not found in DOM.");
        }
        
        // Cache the cancel button from the edit panel specifically.
        cancelVariableEditBtn = document.getElementById('cancelVariableEditBtnInPanel'); 
        if (cancelVariableEditBtn) {
            cancelVariableEditBtn.addEventListener('click', _cancelVariableEdit);
        } else {
            console.warn("VariableManager: Cancel button in variable edit panel (expected ID: #cancelVariableEditBtnInPanel) not found.");
        }

        if (editVariableSendOscOnChangeCheckbox) {
            editVariableSendOscOnChangeCheckbox.addEventListener('change', (event) => {
                _toggleOscConfigGroupVisibility(event.target.checked);
            });
            // Initialize visibility based on current state (though _editVariable also does this)
            // _toggleOscConfigGroupVisibility(editVariableSendOscOnChangeCheckbox.checked);
        } else {
            console.warn("VariableManager: 'Send OSC on Change' checkbox not found in DOM.");
        }

        // Subscribe to config updates from ConfigManager to re-render the list.
        if (App.ConfigManager) {
            App.ConfigManager.subscribe('configLoaded', (config) => {
                console.log("VariableManager: 'configLoaded' event received, refreshing variable list.");
                refresh(config);
            });
            App.ConfigManager.subscribe('configUpdated', (configData) => {
                console.log("VariableManager: 'configUpdated' event received, refreshing variable list.");
                const newConfig = configData.new;
                refresh(newConfig);
                // If a variable edit panel is open, refresh its content to reflect mapping changes
                if (_currentEditingVariableName && newConfig && newConfig.internal_variables) {
                    if (newConfig.internal_variables[_currentEditingVariableName]) {
                        _editVariable(_currentEditingVariableName);
                    } else {
                        // Variable was removed – close the panel
                        _cancelVariableEdit();
                    }
                }
            });
        } else {
            console.error("VariableManager: App.ConfigManager not available for subscribing to config events.");
        }

        // Listen for live variable value updates from the server.
        if (App.SocketManager) {
            App.SocketManager.on('variable_value_updated', _handleVariableValueUpdate);
            console.log("VariableManager: Subscribed to 'variable_value_updated' from SocketManager.");
        } else {
            console.error("VariableManager: App.SocketManager not available for subscribing to 'variable_value_updated'.");
        }

        console.log("VariableManager: Initialization complete.");
    }

    /**
     * Handles the 'variable_value_updated' event from the server.
     * Updates the displayed value of a variable in the list.
     * @param {Object} data - The update data from the server.
     * @param {string} data.name - The name of the variable.
     * @param {number|string} data.value - The new value of the variable.
     */
    function _handleVariableValueUpdate(data) {
        if (!data || typeof data.name === 'undefined' || typeof data.value === 'undefined') {
            console.warn("VariableManager: Received incomplete 'variable_value_updated' event data.", data);
            return;
        }

        const valueElem = document.getElementById(`variable-value-${data.name}`);
        if (valueElem) {
            if (_currentVariablesData && _currentVariablesData[data.name]) {
                _currentVariablesData[data.name].current_value = data.value; // Update local cache.
                
                const variableConfig = _currentVariablesData[data.name];
                let displayParts = [];
                displayParts.push(`Current: ${data.value}`); // Use the new value from the event.

                if (variableConfig.min_value !== undefined && variableConfig.min_value !== null) {
                    displayParts.push(`Min: ${variableConfig.min_value}`);
                }
                if (variableConfig.max_value !== undefined && variableConfig.max_value !== null) {
                    displayParts.push(`Max: ${variableConfig.max_value}`);
                }
                valueElem.textContent = `(${displayParts.join(', ')})`;
            } else {
                // Fallback if cache isn't populated or variable missing (e.g., list not rendered yet).
                valueElem.textContent = `(Current: ${data.value}, Min/Max unknown)`; 
                console.warn(`VariableManager: _currentVariablesData for '${data.name}' not found during live update. Displaying minimal update.`);
            }
        } else {
            // This might happen if the element is not yet rendered or was removed.
            // console.warn(`VariableManager: Value element for variable '${data.name}' (id: variable-value-${data.name}) not found during live update.`);
        }
    }

    /**
     * Public method to refresh the variable list display.
     * Typically called when the configuration changes or when the Variables tab becomes visible.
     * Also handles updating displayed current values if `internal_variables_current_values` is present in the config.
     * @param {Object} config - The full application configuration object.
     */
    function refresh(config) {
        if (!config || !config.internal_variables) {
            _renderVariableList({}, config); // Render an empty list if no variables data.
            return;
        }
        _renderVariableList(config.internal_variables, config); // Render with full variable definitions.
        
        // If the config object also contains a snapshot of current values (e.g., from an initial load),
        // update the display to reflect these potentially more up-to-date current values.
        if (config.internal_variables_current_values) {
            for (const [name, currentValueUpdate] of Object.entries(config.internal_variables_current_values)) {
                const valueElem = document.getElementById(`variable-value-${name}`);
                if (valueElem) {
                    // _currentVariablesData is populated by _renderVariableList call above.
                    // It contains the full config for the variable (initial, min, max etc).
                    const variableConfig = _currentVariablesData[name] || {}; 
                    
                    let displayParts = [];
                    displayParts.push(`Current: ${currentValueUpdate}`); // Prioritize the live/current value.

                    if (variableConfig.min_value !== undefined && variableConfig.min_value !== null) {
                        displayParts.push(`Min: ${variableConfig.min_value}`);
                    }
                    if (variableConfig.max_value !== undefined && variableConfig.max_value !== null) {
                        displayParts.push(`Max: ${variableConfig.max_value}`);
                    }
                    valueElem.textContent = `(${displayParts.join(', ')})`;
                }
            }
        }
    }
    
    // Public API of the VariableManager module.
    return {
        init: init,
        refresh: refresh,
        cancelEdit: _cancelVariableEdit // Expose method to cancel variable edit externally if needed.
    };
})(); 