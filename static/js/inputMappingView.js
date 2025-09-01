// InputMappingView: Manage input mapping UI within layer tabs

window.App = window.App || {};

App.InputMappingView = (function() {
    'use strict';

    let _activeLayerId = 'A'; // Default active layer ID
    let _config = {}; // Stores the full application configuration.
    let _currentRawInputStates = {}; // Stores the latest raw input states from all controllers.
    let _cachedLayerVisualInputs = {}; // Caches visual input DOM elements for each layer, e.g., { layerId: { inputId: element, ... } }
    
    let _rawToGenericInputMap = {}; // Populated from server; maps raw controller input names to generic input IDs.
    let _isInputMapLoaded = false; // Tracks if _rawToGenericInputMap has been loaded.
    
    const ANALOG_INPUT_IDS = new Set([
        "LEFT_STICK_X", "LEFT_STICK_Y", "RIGHT_STICK_X", "RIGHT_STICK_Y",
        "LEFT_TRIGGER", "RIGHT_TRIGGER",
        "ACCEL_X", "ACCEL_Y", "ACCEL_Z",
        "GYRO_X", "GYRO_Y", "GYRO_Z"
    ]);

    const MOTION_CONTROL_GENERIC_IDS = new Set([
        "ACCEL_X", "ACCEL_Y", "ACCEL_Z",
        "GYRO_X", "GYRO_Y", "GYRO_Z"
    ]);

    // UI-only threshold: single deadzone for all analog inputs (sticks, triggers)
    const UI_ANALOG_ACTIVITY_DEADZONE = 0.1; // Visualization only; does not affect processing/mappings

    /**
     * Fetches and stores the raw-to-generic input name mappings from the server.
     * This map is used to translate controller-specific input names to standardized generic IDs.
     * @async
     */
    async function _initializeInputNameMap() {
        if (_isInputMapLoaded) return;
        try {
            const response = await fetch('/api/input-mapping-definitions');
            if (!response.ok) {
                console.error('InputMappingView: Failed to fetch input mapping definitions:', response.status, response.statusText);
                _rawToGenericInputMap = {}; // Fallback to an empty map on error.
                return;
            }
            _rawToGenericInputMap = await response.json();
            _isInputMapLoaded = true;
            console.log('InputMappingView: Successfully loaded input mapping definitions:', _rawToGenericInputMap);
        } catch (error) {
            console.error('InputMappingView: Error fetching input mapping definitions:', error);
            _rawToGenericInputMap = {}; // Fallback to an empty map on error.
        }
    }

    /**
     * Translates a raw input name (from a controller) to a generic input ID used by the UI.
     * Uses the fetched _rawToGenericInputMap.
     * @param {string} rawName - The raw input name from the controller.
     * @returns {string} The generic input ID, or the original rawName if no mapping is found.
     */
    function _getGenericInputNameFromRaw(rawName) {
        return _rawToGenericInputMap[rawName] || rawName; // Use fetched map, or rawName as fallback.
    }
    
    /**
     * Creates a <span> element styled as a label for gamepad input visuals.
     * @param {string} text - The text content for the label.
     * @param {string} [className] - Optional CSS class to apply to the label.
     * @returns {HTMLElement} The created span element.
     */
    function _createLabel(text, className) {
        const label = document.createElement('span');
        label.className = className || '';
        label.textContent = text;
        // Basic styling, can be expanded or moved to CSS
        label.style.position = 'absolute';
        label.style.transform = 'translateX(-50%)';
        label.style.left = '50%';
        label.style.bottom = '-20px'; // Adjust as needed
        label.style.color = '#ccc';
        label.style.fontSize = '10px';
        label.style.textAlign = 'center';
        label.style.pointerEvents = 'none'; // So it doesn't interfere with button clicks
        return label;
    }

    /**
     * Dynamically creates and renders the visual elements for a gamepad 
     * (buttons, sticks, triggers, motion controls) within a specified container for a given layer.
     * @param {string} layerId - The ID of the layer (e.g., 'A', 'B').
     * @param {string} containerId - The ID of the DOM element to contain the gamepad visualization.
     */
    function _initGamepadVisualization(layerId, containerId) {
        const gamepadContainer = document.getElementById(containerId);
        if (!gamepadContainer) {
            console.error(`InputMappingView: Gamepad container #${containerId} not found in the DOM.`);
            return;
        }
        console.log(`InputMappingView: Initializing gamepad visualization in #${containerId}...`);
        gamepadContainer.innerHTML = ''; // Clear previous content
        // Add a background image or base structure if you have one
        gamepadContainer.style.backgroundImage = "url('/static/images/space.jpg')"; // Example
        gamepadContainer.style.backgroundSize = "cover";
        gamepadContainer.style.backgroundRepeat = "no-repeat";
        gamepadContainer.style.backgroundPosition = "center";


        const buttonPositions = {
            'GAMEPAD_A': { top: '74%', left: '85%', label: 'A' },      
            'GAMEPAD_B': { top: '65%', left: '92%', label: 'B' },      
            'GAMEPAD_X': { top: '65%', left: '78%', label: 'X' },      
            'GAMEPAD_Y': { top: '56%', left: '85%', label: 'Y' },      
            'LEFT_SHOULDER': { top: '21%', left: '18.7%', label: 'LB' }, 
            'RIGHT_SHOULDER': { top: '21%', left: '80.7%', label: 'RB' }, 
            'START_BUTTON': { top: '45%', left: '60%' , label: 'Start'}, 
            'SELECT_BUTTON': { top: '45%', left: '40%', label: 'Back' },   
            'LEFT_STICK_PRESS': { top: '45%', left: '25%', label: 'L3' },  
            'RIGHT_STICK_PRESS': { top: '70%', left: '65%', label: 'R3' }, 
            'DPAD_UP':    { top: '56%', left: '12%', label: 'Up' },   
            'DPAD_DOWN':  { top: '74%', left: '12%', label: 'Down' }, 
            'DPAD_LEFT':  { top: '65%', left: '5%',  label: 'Left' }, 
            'DPAD_RIGHT': { top: '65%', left: '19%', label: 'Right' } 
        };
        
        for (const [buttonId, pos] of Object.entries(buttonPositions)) {
            const btnContainer = document.createElement('div');
            btnContainer.style.position = 'absolute';
            btnContainer.style.top = pos.top;
            btnContainer.style.left = pos.left;
            btnContainer.style.transform = 'translate(-50%, -50%)'; // Center the button/container

            const elem = document.createElement('div');
            elem.className = 'button gamepad-input unmapped'; // Added gamepad-input for common styling/selection
            elem.id = `${layerId}-${buttonId}`; // Ensure unique IDs per layer if needed, or use data-attributes
            elem.dataset.inputId = buttonId;
            elem.dataset.layerId = layerId;
            elem.onclick = () => _handleInputSelection(buttonId, layerId);
            btnContainer.appendChild(elem);

            const label = _createLabel(pos.label || buttonId.replace('_', ' '), 'button-label');
            btnContainer.appendChild(label);

            gamepadContainer.appendChild(btnContainer);
        }
        
        const stickComponentAnchors = {
            'LEFT_STICK_PRESS':  { 
                x_id: 'LEFT_STICK_X',  y_id: 'LEFT_STICK_Y',  
                // Offsets are relative to the anchor point (center of the thumbstick button)
                x_offset: { top: '15px', left: '45px' }, // Move X to the right
                y_offset: { top: '-15px', left: '15px' }  // Move Y upwards
            },
            'RIGHT_STICK_PRESS': { 
                x_id: 'RIGHT_STICK_X', y_id: 'RIGHT_STICK_Y', 
                x_offset: { top: '15px', left: '45px' }, 
                y_offset: { top: '-15px', left: '15px' } 
            }
        };

        for (const [anchorButtonId, componentIds] of Object.entries(stickComponentAnchors)) {
            const anchorPos = buttonPositions[anchorButtonId];
            if (!anchorPos) {
                console.warn(`Anchor button ${anchorButtonId} for stick components not found in buttonPositions.`);
                continue;
            }

            // Create a container relative to the anchor's main button position
            // This helps keep X/Y components grouped with their thumbstick visual
            const stickGroupContainer = document.createElement('div');
            stickGroupContainer.style.position = 'absolute';
            stickGroupContainer.style.top = anchorPos.top; 
            stickGroupContainer.style.left = anchorPos.left;
            stickGroupContainer.style.transform = 'translate(-50%, -50%)'; // Align with the anchor button center

            const xButton = document.createElement('div');
            xButton.className = 'stick-component gamepad-input unmapped'; 
            xButton.id = `${layerId}-${componentIds.x_id}`;
            xButton.dataset.inputId = componentIds.x_id;
            xButton.dataset.layerId = layerId;
            xButton.style.position = 'absolute'; // Position relative to stickGroupContainer
            xButton.style.left = componentIds.x_offset.left; 
            xButton.style.top = componentIds.x_offset.top;   
            xButton.style.transform = 'translate(-50%, -50%)'; 
            xButton.innerHTML = `<span class="stick-component-label">X</span>`;
            xButton.onclick = () => _handleInputSelection(componentIds.x_id, layerId);
            
            const yButton = document.createElement('div');
            yButton.className = 'stick-component gamepad-input unmapped'; 
            yButton.id = `${layerId}-${componentIds.y_id}`;
            yButton.dataset.inputId = componentIds.y_id;
            yButton.dataset.layerId = layerId;
            yButton.style.position = 'absolute'; // Position relative to stickGroupContainer
            yButton.style.left = componentIds.y_offset.left;  
            yButton.style.top = componentIds.y_offset.top; 
            yButton.style.transform = 'translate(-50%, -50%)'; 
            yButton.innerHTML = `<span class="stick-component-label">Y</span>`;
            yButton.onclick = () => _handleInputSelection(componentIds.y_id, layerId);

            stickGroupContainer.appendChild(xButton);
            stickGroupContainer.appendChild(yButton);
            gamepadContainer.appendChild(stickGroupContainer);
        }
        
        const triggerPositions = {
            'LEFT_TRIGGER': { top: '8%', left: '18%', label: 'LT' },   
            'RIGHT_TRIGGER': { top: '8%', left: '80%', label: 'RT' } 
        };
        
        for (const [triggerId, pos] of Object.entries(triggerPositions)) {
            const trigContainer = document.createElement('div');
            trigContainer.style.position = 'absolute';
            trigContainer.style.top = pos.top;
            trigContainer.style.left = pos.left;
            trigContainer.style.transform = 'translate(-50%, -50%)';

            const elem = document.createElement('div');
            elem.className = 'trigger gamepad-input unmapped'; 
            elem.id = `${layerId}-${triggerId}`;
            elem.dataset.inputId = triggerId;
            elem.dataset.layerId = layerId;
            elem.onclick = () => _handleInputSelection(triggerId, layerId);
            trigContainer.appendChild(elem);

            const label = _createLabel(pos.label, 'trigger-label');
            trigContainer.appendChild(label);

            gamepadContainer.appendChild(trigContainer);
        }

        // --- START: Add Motion Controls ---
        const motionControlIds = {
            'ACCEL_X': 'Accel X',
            'ACCEL_Y': 'Accel Y',
            'ACCEL_Z': 'Accel Z',
            'GYRO_X': 'Gyro X',
            'GYRO_Y': 'Gyro Y',
            'GYRO_Z': 'Gyro Z'
        };

        const motionGridContainerId = `motion-controls-grid-layer-${layerId.toLowerCase()}`;
        const motionGridContainer = document.getElementById(motionGridContainerId);

        if (motionGridContainer) {
            motionGridContainer.innerHTML = ''; // Clear previous content
            for (const [id, displayLabel] of Object.entries(motionControlIds)) {
                const item = document.createElement('div');
                item.className = 'motion-control-item gamepad-input unmapped'; // Added gamepad-input for common selection/update logic
                item.id = `${layerId}-${id}`; // e.g., A-ACCEL_X
                item.dataset.inputId = id;
                item.dataset.layerId = layerId;
                item.onclick = () => _handleInputSelection(id, layerId);

                const labelEl = document.createElement('div');
                labelEl.className = 'motion-label';
                labelEl.textContent = displayLabel;

                const valueEl = document.createElement('div');
                valueEl.className = 'value-display';
                valueEl.textContent = '0.00'; // Placeholder value
                item.dataset.valueDisplay = "true"; // Mark that this element should show live values (handled elsewhere)

                item.appendChild(labelEl);
                item.appendChild(valueEl);
                motionGridContainer.appendChild(item);
            }
        } else {
            console.warn(`InputMappingView: Motion control grid container #${motionGridContainerId} not found.`);
        }
        // --- END: Add Motion Controls ---

        _updateGamepadInputStates(layerId, gamepadContainer, motionGridContainer);
    }

    /**
     * Processes raw input state updates from the backend.
     * Determines the activity and value for each generic input based on all connected controllers
     * and updates the visual elements on the active layer accordingly.
     * @param {Object} rawStatesData - An object where keys are controller IDs and values are objects
     *                                 of raw input names to their states (boolean or number).
     *                                 Example: { "XInput0": { "A": true, "LEFT_STICK_X": 0.5 }, ... }
     */
    function _handleRawInputUpdate(rawStatesData) {
        if (!rawStatesData) {
            console.warn("InputMappingView: _handleRawInputUpdate called with no data.");
            return;
        }
        _currentRawInputStates = rawStatesData;

        const activeLayerCache = _cachedLayerVisualInputs[_activeLayerId];
        if (!activeLayerCache) {
            return;
        }

        // Stores the determined active state and value for each genericInputId.
        const genericInputActivity = {};
        
        // First, determine the activity state for all relevant generic inputs
        // based on the current raw states from all controllers.
        for (const controllerId in _currentRawInputStates) {
            if (!_currentRawInputStates.hasOwnProperty(controllerId) || !_currentRawInputStates[controllerId]) {
                continue;
            }
            const controllerState = _currentRawInputStates[controllerId];
            for (const rawInputName in controllerState) {
                if (!controllerState.hasOwnProperty(rawInputName)) {
                    continue;
                }

                const genericInputId = _getGenericInputNameFromRaw(rawInputName);
                const rawValue = controllerState[rawInputName];

                // Initialize if this genericInputId hasn't been seen yet.
                if (!genericInputActivity[genericInputId]) {
                    genericInputActivity[genericInputId] = { isActive: false, value: 0 };
                }

                // Update activity if this raw input makes it active.
                // This logic ensures that if any mapped raw input is active, the generic input is considered active.
                let currentRawActive = false;
                let currentRawValue = 0;

                if (typeof rawValue === 'number') {
                    currentRawValue = rawValue;
                    if (Math.abs(rawValue) >= UI_ANALOG_ACTIVITY_DEADZONE) { // Consider active only above UI threshold.
                        currentRawActive = true;
                    }
                } else if (typeof rawValue === 'boolean' && rawValue) {
                    currentRawActive = true;
                    currentRawValue = 1.0; // Standardize boolean true to a numeric value for display.
                }

                if (currentRawActive) {
                    genericInputActivity[genericInputId].isActive = true;
                    // For simplicity, take the first active rawValue.
                    // More complex logic could average or sum if multiple raw inputs map to one generic.
                    if (genericInputActivity[genericInputId].value === 0) { // Prioritize non-zero if multiple raw inputs map here.
                         genericInputActivity[genericInputId].value = currentRawValue;
                    }
                } else {
                    // If not active, but no other raw input has made it active yet, store its value.
                    if (!genericInputActivity[genericInputId].isActive && genericInputActivity[genericInputId].value === 0) {
                        genericInputActivity[genericInputId].value = currentRawValue;
                    }
                }
            }
        }

        // Now, iterate through the cached visual elements and update them
        // based on the determined activity of their genericInputId.
        for (const genericInputId in activeLayerCache) {
            if (!activeLayerCache.hasOwnProperty(genericInputId)) {
                continue;
            }
            const visualElement = activeLayerCache[genericInputId];
            if (!visualElement) continue;

            const activity = genericInputActivity[genericInputId] || { isActive: false, value: 0 }; // Default if no raw input mapped to it

            if (visualElement.dataset.valueDisplay === "true") {
                const valueDisplayChild = visualElement.querySelector('.value-display');
                if (valueDisplayChild) {
                    valueDisplayChild.textContent = activity.value.toFixed(2);
                }
            }

            // Apply active class only if the input is active AND it's not a motion control ID
            if (activity.isActive && !MOTION_CONTROL_GENERIC_IDS.has(genericInputId)) {
                visualElement.classList.add('active');
                visualElement.classList.remove('inactive');
            } else {
                visualElement.classList.remove('active');
                visualElement.classList.add('inactive');
            }
        }
    }

    /**
     * Handles click events on gamepad visual inputs.
     * Sets the selected input in ConfigManager and triggers the rendering 
     * of the mapping configuration panel for that input.
     * @param {string} inputId - The generic ID of the selected input (e.g., "A", "LEFT_STICK_X").
     * @param {string} layerId - The ID of the layer where the input was selected.
     */
    function _handleInputSelection(inputId, layerId) {
        console.log(`InputMappingView: Input selected via click: ${inputId} on Layer: ${layerId}`);
        App.ConfigManager.setSelectedInput({ inputId: inputId, layerId: layerId }); 
        
        // The selection visual update is handled by _updateGamepadInputStates,
        // triggered by 'selectedInputChanged' or 'configUpdated' events from ConfigManager.

        const mappingConfigArea = document.getElementById(`input-mapping-config-area-${layerId.toLowerCase()}`); 
        if(mappingConfigArea){
            _renderMappingConfigPanel(mappingConfigArea, layerId, inputId);
        } else {
            console.error(`Mapping config area for layer ${layerId} not found.`);
        }
    }

    /**
     * Renders the configuration form for a selected input within the provided parent element.
     * Populates the form with current mapping data for the input.
     * @param {HTMLElement} parentElement - The DOM element to host the mapping configuration form.
     * @param {string} layerId - The ID of the layer for the mapping.
     * @param {string} inputId - The generic ID of the input being configured.
     */
    function _renderMappingConfigPanel(parentElement, layerId, inputId){
        const currentConfig = App.ConfigManager.getConfig();
        const currentMapping = currentConfig.layers?.[layerId]?.input_mappings?.[inputId] || {};
        const params = currentMapping.params || {};

        // Clear existing content first
        parentElement.innerHTML = ''; 

        const form = document.createElement('form');
        form.id = `input-mapping-form-${layerId}-${inputId}`;
        form.className = 'space-y-4 p-4 bg-gray-800 rounded-md border border-gray-700';

        const heading = document.createElement('h4');
        heading.className = 'text-lg font-semibold text-purple-300';
        heading.textContent = `Map '${inputId}' (Layer ${layerId})`;
        form.appendChild(heading);

        // 1. Target Type Dropdown
        const targetTypeDiv = document.createElement('div');
        const targetTypeLabel = document.createElement('label');
        targetTypeLabel.className = 'form-label';
        targetTypeLabel.textContent = 'Target Type:';
        targetTypeDiv.appendChild(targetTypeLabel);
        const targetTypeSelect = document.createElement('select');
        targetTypeSelect.id = `mapping-target-type-${layerId}-${inputId}`;
        targetTypeSelect.className = 'select-default';
        [
            { value: '', text: '-- Select Target Type --' },
            { value: 'osc_channel', text: 'OSC Channel' },
            { value: 'internal_variable', text: 'Internal Variable' },
            { value: 'layer_switch', text: 'Switch Layer' }
        ].forEach(opt => {
            const option = document.createElement('option');
            option.value = opt.value;
            option.textContent = opt.text;
            if ((!currentMapping.target_type && opt.value === 'osc_channel') || currentMapping.target_type === opt.value) {
                 // Default to OSC Channel if no type currently, or select the current type.
                 // Ensure the first option (placeholder) is selected if currentMapping.target_type is null/undefined and opt.value is also the placeholder.
                if (!(!currentMapping.target_type && opt.value === '')) { // Inverted condition to simplify selection
                    option.selected = true;
                }
            }
            targetTypeSelect.appendChild(option);
        });
        targetTypeDiv.appendChild(targetTypeSelect);
        form.appendChild(targetTypeDiv);
        
        // 2. Target Name Container (populated by _populateTargetDropdown)
        const targetNameContainerDiv = document.createElement('div');
        targetNameContainerDiv.id = `mapping-target-container-${layerId}-${inputId}`;
        form.appendChild(targetNameContainerDiv);

        // 3. Action/Mode Dropdown Container (populated by _populateActionDropdown)
        const actionContainerDiv = document.createElement('div');
        actionContainerDiv.id = `mapping-action-container-${layerId}-${inputId}`;
        form.appendChild(actionContainerDiv);

        // 4. Action Parameters Container (populated by _populateActionParameters)
        const paramsContainerDiv = document.createElement('div');
        paramsContainerDiv.id = `mapping-params-container-${layerId}-${inputId}`;
        paramsContainerDiv.className = 'space-y-3';
        form.appendChild(paramsContainerDiv);

        // 5. Invert Mapping Checkbox
        const invertDiv = document.createElement('div');
        invertDiv.id = `mapping-invert-container-${layerId}-${inputId}`;
        invertDiv.className = 'flex items-center mt-3';
        const invertCheckbox = document.createElement('input');
        invertCheckbox.type = 'checkbox';
        invertCheckbox.id = `mapping-invert-${layerId}-${inputId}`;
        invertCheckbox.name = 'mapping-invert';
        invertCheckbox.className = 'form-checkbox h-5 w-5 text-purple-600';
        invertCheckbox.checked = !!params.invert;
        invertDiv.appendChild(invertCheckbox);
        const invertLabel = document.createElement('label');
        invertLabel.htmlFor = invertCheckbox.id;
        invertLabel.className = 'ml-2 form-label-inline';
        invertLabel.textContent = 'Invert Mapping (Min/Max)';
        invertDiv.appendChild(invertLabel);
        form.appendChild(invertDiv);
        
        // 6. Save to All Layers Checkbox
        const saveAllDiv = document.createElement('div');
        saveAllDiv.className = 'flex items-center mt-3';
        const saveAllCheckbox = document.createElement('input');
        saveAllCheckbox.type = 'checkbox';
        saveAllCheckbox.id = `mapping-save-all-layers-${layerId}-${inputId}`;
        saveAllCheckbox.name = 'mapping-save-all-layers';
        saveAllCheckbox.className = 'form-checkbox h-5 w-5 text-purple-600';
        saveAllDiv.appendChild(saveAllCheckbox);
        const saveAllLabel = document.createElement('label');
        saveAllLabel.htmlFor = saveAllCheckbox.id;
        saveAllLabel.className = 'ml-2 form-label-inline';
        saveAllLabel.textContent = 'Save to ALL Layers';
        saveAllDiv.appendChild(saveAllLabel);
        form.appendChild(saveAllDiv);

        // 7. Buttons
        const buttonsDiv = document.createElement('div');
        buttonsDiv.className = 'flex justify-end space-x-2 pt-3';
        const clearButton = document.createElement('button');
        clearButton.type = 'button';
        clearButton.id = `clear-mapping-btn-${layerId}-${inputId}`;
        clearButton.className = 'btn btn-danger';
        clearButton.textContent = 'Clear Mapping';
        buttonsDiv.appendChild(clearButton);

        const cancelButton = document.createElement('button'); // New Cancel Button
        cancelButton.type = 'button';
        cancelButton.id = `cancel-mapping-btn-${layerId}-${inputId}`;
        cancelButton.className = 'btn btn-secondary'; // Assuming a secondary style
        cancelButton.textContent = 'Cancel';
        buttonsDiv.appendChild(cancelButton);

        const saveButton = document.createElement('button');
        saveButton.type = 'submit';
        saveButton.className = 'btn btn-primary';
        saveButton.textContent = 'Save Mapping';
        buttonsDiv.appendChild(saveButton);
        form.appendChild(buttonsDiv);
        
        parentElement.appendChild(form);

        // Add event listeners and perform initial population of dynamic form parts.
            targetTypeSelect.addEventListener('change', (e) => {
            const selectedTargetType = e.target.value;
            // When target type changes: repopulate target names, then actions, then clear params.
            _populateTargetDropdown(layerId, inputId, selectedTargetType);     // Target name dropdown depends on target type.
            // _populateActionDropdown is called by _populateTargetDropdown's change listener or initial population.
                document.getElementById(`mapping-params-container-${layerId}-${inputId}`).innerHTML = ''; // Clear parameters section.
                // If switching to layer_switch, check 'Save to ALL Layers' by default
                const saveAllCb = document.getElementById(`mapping-save-all-layers-${layerId}-${inputId}`);
                if (saveAllCb) {
                    saveAllCb.checked = (selectedTargetType === 'layer_switch');
                }
            });

        // Initial population calls based on the current mapping (if any).
        if (currentMapping.target_type) {
            targetTypeSelect.value = currentMapping.target_type; // Ensure correct type is selected.
                 _populateTargetDropdown(layerId, inputId, currentMapping.target_type);
            // _populateActionDropdown is typically called within _populateTargetDropdown (e.g., for OSC)
            // or by its event listener after a target name is selected.
            // A direct call might be needed here if target_name is already known and is NOT OSC type.
            if (currentMapping.target_name && currentMapping.target_type !== 'osc_channel') {
                 _populateActionDropdown(layerId, inputId, currentMapping.target_type, currentMapping.target_name);
            }
            // Default the 'Save to ALL Layers' to checked only for layer_switch
            const saveAllCbInit = document.getElementById(`mapping-save-all-layers-${layerId}-${inputId}`);
            if (saveAllCbInit) {
                saveAllCbInit.checked = (currentMapping.target_type === 'layer_switch');
            }
        } else {
            // If no target type is currently set, populate with default (which then triggers action population).
            _populateTargetDropdown(layerId, inputId, targetTypeSelect.value);
            const saveAllCbInit = document.getElementById(`mapping-save-all-layers-${layerId}-${inputId}`);
            if (saveAllCbInit) {
                saveAllCbInit.checked = (targetTypeSelect.value === 'layer_switch');
            }
        }
        
            form.addEventListener('submit', (e) => _handleSaveMapping(e, layerId, inputId));
            clearButton.addEventListener('click', () => _handleClearMapping(layerId, inputId));
            cancelButton.addEventListener('click', () => {
                const mappingConfigArea = document.getElementById(`input-mapping-config-area-${layerId.toLowerCase()}`);
                if(mappingConfigArea) {
                    mappingConfigArea.innerHTML = '<p class="text-gray-400 italic">Select an input to configure its mapping.</p>';
                }
                App.ConfigManager.setSelectedInput(null);
            });
    }

    /**
     * Populates the "Target Name" part of the mapping form based on the selected `targetType`.
     * For OSC, it creates checkboxes for available channels. For other types, it creates a select dropdown.
     * @param {string} layerId - The ID of the layer.
     * @param {string} inputId - The generic ID of the input.
     * @param {string} targetType - The selected target type (e.g., 'osc_channel', 'internal_variable').
     */
    function _populateTargetDropdown(layerId, inputId, targetType){
        const container = document.getElementById(`mapping-target-container-${layerId}-${inputId}`);
        if(!container) return;
        container.innerHTML = ''; // Clear previous content
        
        const currentConfig = App.ConfigManager.getConfig();
        const currentMapping = App.ConfigManager.getMappingForInput(layerId, inputId) || {};
        let targetNameValue = currentMapping.target_name; // Can be a string or an array (for OSC channels).

        const labelEl = document.createElement('label'); // Use 'labelEl' to avoid conflict with 'label' in loops.
        labelEl.className = 'form-label';
        labelEl.textContent = 'Target Name:';
        container.appendChild(labelEl);

        if (targetType === 'osc_channel') {
            const checkboxContainer = document.createElement('div');
            checkboxContainer.id = `mapping-target-name-osc-container-${layerId}-${inputId}`;
            checkboxContainer.className = 'osc-channel-checkbox-container mt-1 space-y-0.5'; 

            const channels = currentConfig.internal_channels || {};
            const selectedChannels = Array.isArray(targetNameValue) ? targetNameValue : (targetNameValue ? [targetNameValue] : []);

            if (Object.keys(channels).length === 0) {
                const noChannelsMsg = document.createElement('p');
                noChannelsMsg.className = 'text-xs text-gray-400 italic';
                noChannelsMsg.textContent = 'No OSC channels defined yet.';
                checkboxContainer.appendChild(noChannelsMsg);
            } else {
                // Optional header row
                const headerRow = document.createElement('div');
                headerRow.className = 'grid grid-cols-12 gap-1 px-2 py-0.5 text-xs text-gray-400';
                headerRow.innerHTML = `
                    <div class="col-span-1"></div>
                    <div class="col-span-3">Name</div>
                    <div class="col-span-5">OSC Address</div>
                    <div class="col-span-3">On Value</div>
                `;
                checkboxContainer.appendChild(headerRow);

                const channelEntries = Object.entries(channels).sort(([aName], [bName]) => aName.localeCompare(bName));
                channelEntries.forEach(([channelName, channelData]) => {
                    const channelWrapper = document.createElement('div');
                    channelWrapper.className = 'grid grid-cols-12 items-center gap-1 px-2 py-0.5 hover:bg-gray-700/30 rounded';

                    const checkboxCell = document.createElement('div');
                    checkboxCell.className = 'col-span-1 flex items-center';
                    const checkbox = document.createElement('input');
                    checkbox.type = 'checkbox';
                    checkbox.id = `mapping-target-osc-${layerId}-${inputId}-${channelName}`;
                    checkbox.value = channelName;
                    checkbox.name = `mapping-target-osc-${layerId}-${inputId}`; // Group checkboxes for form submission.
                    checkbox.className = 'form-checkbox h-4 w-4 text-purple-600';
                    if (selectedChannels.includes(channelName)) {
                        checkbox.checked = true;
                    }
                    checkbox.addEventListener('change', () => {
                        const selected = Array.from(checkboxContainer.querySelectorAll('input[type="checkbox"]:checked')).map(cb => cb.value);
                        _populateActionDropdown(layerId, inputId, targetType, selected);
                    });
                    checkboxCell.appendChild(checkbox);
                    channelWrapper.appendChild(checkboxCell);

                    const nameCell = document.createElement('label');
                    nameCell.htmlFor = checkbox.id;
                    nameCell.className = 'col-span-3 text-sm text-gray-200 truncate';
                    nameCell.textContent = channelName;
                    channelWrapper.appendChild(nameCell);

                    const addr = (channelData && channelData.osc_address) ? channelData.osc_address : '';
                    const addrCell = document.createElement('div');
                    addrCell.className = 'col-span-5 text-xs text-gray-400 font-mono truncate';
                    addrCell.title = addr || '';
                    addrCell.textContent = addr || '';
                    channelWrapper.appendChild(addrCell);

                    // Derive a sensible "On" value preview
                    let onValueDisplay = '';
                    try {
                        const oscType = channelData && channelData.osc_type ? String(channelData.osc_type) : 'float';
                        if (oscType === 'string') {
                            const strs = Array.isArray(channelData && channelData.osc_strings) ? channelData.osc_strings : [];
                            onValueDisplay = (strs.length > 1 ? String(strs[1]) : (strs.length > 0 ? String(strs[0]) : ''));
                        } else {
                            if (channelData && Array.isArray(channelData.range) && channelData.range.length === 2) {
                                onValueDisplay = String(channelData.range[1]);
                            } else if (channelData && (channelData.max_value !== undefined || channelData.range_max !== undefined)) {
                                onValueDisplay = String(channelData.max_value !== undefined ? channelData.max_value : channelData.range_max);
                            } else {
                                onValueDisplay = '';
                            }
                        }
                    } catch (e) { onValueDisplay = ''; }

                    const onCell = document.createElement('div');
                    onCell.className = 'col-span-3 text-xs text-gray-300 truncate';
                    onCell.title = onValueDisplay;
                    onCell.textContent = onValueDisplay;
                    channelWrapper.appendChild(onCell);

                    checkboxContainer.appendChild(channelWrapper);
                });
            }
            container.appendChild(checkboxContainer);
            
            // Initial population of action dropdown after creating checkboxes
            const initiallySelected = Array.from(checkboxContainer.querySelectorAll('input[type="checkbox"]:checked'))
                                       .map(cb => cb.value);
            _populateActionDropdown(layerId, inputId, targetType, initiallySelected);

        } else { // For 'internal_variable' and 'layer_switch' target types.
            const select = document.createElement('select');
            select.id = `mapping-target-name-${layerId}-${inputId}`;
            select.className = 'select-default';
            
            let options = [];
            if (targetType === 'internal_variable') {
                options.push({ value: '', text: '-- Select Variable --' });
            const variables = currentConfig.internal_variables || {};
                for (const varName in variables) {
                    options.push({ value: varName, text: varName, selected: targetNameValue === varName });
            }
            } else if (targetType === 'layer_switch') {
                options.push({ value: '', text: '-- Select Layer --' });
                const layers = ['A', 'B', 'C', 'D'];
                for (const l_id of layers) {
                    options.push({ value: l_id, text: `Layer ${l_id}`, selected: targetNameValue === l_id });
            }
            } else { // Fallback if targetType is unexpected.
                 options.push({ value: '', text: '-- Select Target First --'});
            }

            options.forEach(optData => {
                const option = document.createElement('option');
                option.value = optData.value;
                option.textContent = optData.text;
                if (optData.selected) {
                    option.selected = true;
                }
                select.appendChild(option);
            });
            container.appendChild(select);

            select.addEventListener('change', (e) => {
                 _populateActionDropdown(layerId, inputId, targetType, e.target.value);
                // Parameter UI is handled by _populateActionParameters.
            });
            
            // Initial population for select-based targets.
            if (targetNameValue) { // Only if a target was already selected.
                 _populateActionDropdown(layerId, inputId, targetType, targetNameValue);
            } else { // If no target was selected, ensure action dropdown is in its initial state for this target type.
                 _populateActionDropdown(layerId, inputId, targetType, '');
            }
        }
    }

    /**
     * Populates the "Action/Mode" dropdown in the mapping form based on the selected `targetType` and `targetNameOrNames`.
     * For 'internal_variable', no action dropdown is shown as it has a fixed action; instead, parameters are directly populated.
     * @param {string} layerId - The ID of the layer.
     * @param {string} inputId - The generic ID of the input.
     * @param {string} targetType - The selected target type.
     * @param {string|string[]} targetNameOrNames - The selected target name(s).
     */
    function _populateActionDropdown(layerId, inputId, targetType, targetNameOrNames){
        const actionContainer = document.getElementById(`mapping-action-container-${layerId}-${inputId}`);
        if (!actionContainer) {
            console.error(`Action container mapping-action-container-${layerId}-${inputId} not found!`);
            return;
        }
        actionContainer.innerHTML = ''; // Always clear previous content first.

        const currentMapping = App.ConfigManager.getMappingForInput(layerId, inputId) || {};
        const currentAction = currentMapping.action || ''; 

        const targetIsSelected = Array.isArray(targetNameOrNames) ? targetNameOrNames.length > 0 : !!targetNameOrNames;

        if (targetType === 'internal_variable') {
            // Internal variables always use 'step_by_multiplier_on_trigger' action implicitly.
            if (targetIsSelected) {
                _populateActionParameters(layerId, inputId, targetType, targetNameOrNames, 'step_by_multiplier_on_trigger');
            } else {
                const hint = document.createElement('p');
                hint.className = 'text-xs text-gray-400 mt-1 italic';
                hint.textContent = 'Select a variable above to configure its step multiplier.';
                actionContainer.appendChild(hint);
                const paramsContainer = document.getElementById(`mapping-params-container-${layerId}-${inputId}`);
                if (paramsContainer) paramsContainer.innerHTML = ''; // Clear params if no variable selected.
            }
            return; // No action dropdown for internal_variable.
        } else if (targetType === 'layer_switch') {
            // Layer switch has a single action: activate_layer. No dropdown needed.
            if (targetIsSelected) {
                _populateActionParameters(layerId, inputId, targetType, targetNameOrNames, 'activate_layer');
            } else {
                const hint = document.createElement('p');
                hint.className = 'text-xs text-gray-400 mt-1 italic';
                hint.textContent = 'Select a layer above to activate on press.';
                actionContainer.appendChild(hint);
                const paramsContainer = document.getElementById(`mapping-params-container-${layerId}-${inputId}`);
                if (paramsContainer) paramsContainer.innerHTML = '';
            }
            return; // No action dropdown for layer_switch.
        } else {
            // This block executes for target types other than 'internal_variable'.
            const label = document.createElement('label');
            label.htmlFor = `action-select-${layerId}-${inputId}`;
            label.className = 'form-label';
            label.textContent = 'Action/Mode:';
            actionContainer.appendChild(label);
    
            const actionSelect = document.createElement('select');
            actionSelect.id = `action-select-${layerId}-${inputId}`;
            actionSelect.className = 'select-default';
            actionContainer.appendChild(actionSelect);
    
            const allActionOptions = [
                { value: 'direct', label: 'Direct Value' },
                { value: 'toggle', label: 'Toggle Values' },
                { value: 'rate', label: 'Rate' },
                { value: 'step_by_multiplier_on_trigger', label: 'Step by Multiplier on Trigger'},
                { value: 'reset_channel_on_trigger', label: 'Reset Channel to Default'},
                { value: 'set_value_from_input', label: 'Set from Input (Variable)' }, 
                { value: 'activate_layer', label: 'Activate Layer (Hold)' }
            ];
    
            let actionsToShow = [];
    
            if (targetType && targetIsSelected) { 
                if (targetType === 'osc_channel') {
                    actionsToShow = allActionOptions.filter(opt => ![
                        'set_value_from_input', 
                        'activate_layer'
                    ].includes(opt.value));
                } else if (targetType === 'layer_switch') {
                    console.log(`IMV_populateActionDropdown (LayerSwitch): layerId=${layerId}, inputId=${inputId}, targetType=${targetType}, targetNameOrNames=${JSON.stringify(targetNameOrNames)}, currentAction=${currentAction}`);
                    actionsToShow = allActionOptions.filter(opt => [
                        'activate_layer'
                    ].includes(opt.value));
                }
                
                if (actionsToShow.length > 0) {
                    actionsToShow.unshift({ value: '', label: '-- Select Action --' });
                }
            } 
            
            if (actionsToShow.length === 0) {
                actionsToShow = [{ value: '', label: '-- Select Target Name First --' }];
            }
    
            if (targetType === 'layer_switch') {
                console.log('IMV_populateActionDropdown (LayerSwitch): actionsToShow after filter:', JSON.parse(JSON.stringify(actionsToShow)));
            }
    
            actionsToShow.forEach(actionData => {
                const option = document.createElement('option');
                option.value = actionData.value;
                option.textContent = actionData.label;
                if (currentAction === actionData.value) {
                    option.selected = true;
                    if (targetType === 'layer_switch') {
                        console.log(`IMV_populateActionDropdown (LayerSwitch): Matched currentAction '${currentAction}' with option '${actionData.value}'. Setting selected.`);
                    }
                }
                actionSelect.appendChild(option);
            });
    
            actionSelect.removeEventListener('change', _populateActionParametersFromEvent); // Ensure no duplicate listeners.
            actionSelect.addEventListener('change', _populateActionParametersFromEvent);
            
            // Populate parameters for the initially selected (or default) action.
            _populateActionParameters(layerId, inputId, targetType, targetNameOrNames, actionSelect.value);
        } // Closes the main 'else' block for non-internal_variable types.
    }

    /**
     * Event handler for the 'change' event on the action dropdown.
     * Gathers necessary context (layerId, inputId, targetType, targetName) from the form 
     * and calls _populateActionParameters to update the parameter UI.
     * @param {Event} event - The 'change' event object from the action select element.
     */
    function _populateActionParametersFromEvent(event) {
        const selectElement = event.target; // This is the actionSelect element.
        const form = selectElement.closest('form');
        if (!form) {
            console.error('IMV_populateActionParametersFromEvent: Could not find parent form for action select:', selectElement);
            return;
        }
        const formIdParts = form.id.split('-'); // e.g., "input-mapping-form-A-RIGHT_TRIGGER"
        const layerId = formIdParts[3];
        const inputId = formIdParts.slice(4).join('-');

        const targetTypeSelect = form.querySelector(`#mapping-target-type-${layerId}-${inputId}`);
        
        if (!targetTypeSelect) {
            console.error(`IMV_populateActionParametersFromEvent: Could not find target type select (#mapping-target-type-${layerId}-${inputId})`);
            return;
        }

        const selectedActionValue = selectElement.value;
        const selectedTargetTypeValue = targetTypeSelect.value;
        let targetNameValue;

        if (selectedTargetTypeValue === 'osc_channel') {
            const oscContainer = form.querySelector(`#mapping-target-name-osc-container-${layerId}-${inputId}`);
            if (oscContainer) {
                targetNameValue = Array.from(oscContainer.querySelectorAll('input[type="checkbox"]:checked')).map(cb => cb.value);
                // If no checkboxes are selected, targetNameValue will be an empty array.
                // This is acceptable as _populateActionParameters might not need targetName for some actions,
                // or it might handle an empty array appropriately.
            } else {
                console.error(`IMV_populateActionParametersFromEvent: Could not find OSC target name container (#mapping-target-name-osc-container-${layerId}-${inputId})`);
                targetNameValue = []; // Default to empty array if container not found to avoid errors.
            }
        } else {
            // For 'internal_variable' and 'layer_switch'.
            const targetNameSelectElement = form.querySelector(`#mapping-target-name-${layerId}-${inputId}`);
            if (targetNameSelectElement) {
                targetNameValue = targetNameSelectElement.value;
            } else {
                console.error(`IMV_populateActionParametersFromEvent: Could not find target name select (#mapping-target-name-${layerId}-${inputId}) for type ${selectedTargetTypeValue}`);
                // targetNameValue will be undefined; _populateActionParameters should handle this.
            }
        }
        
        _populateActionParameters(layerId, inputId, selectedTargetTypeValue, targetNameValue, selectedActionValue);
    }

    /**
     * Dynamically creates and populates the UI elements for action-specific parameters
     * in the mapping form (e.g., input fields for 'rate_multiplier', 'step-value').
     * @param {string} layerId - The ID of the layer.
     * @param {string} inputId - The generic ID of the input.
     * @param {string} targetType - The selected target type.
     * @param {string|string[]} targetNameOrNames - The selected target name(s).
     * @param {string} action - The selected action/mode.
     */
    function _populateActionParameters(layerId, inputId, targetType, targetNameOrNames, action){
        const paramsContainer = document.getElementById(`mapping-params-container-${layerId}-${inputId}`);
        if(!paramsContainer) return;
        paramsContainer.innerHTML = ''; // Clear previous parameters.
        
        const currentMapping = App.ConfigManager.getMappingForInput(layerId, inputId) || {};
        const currentMappingParams = currentMapping.params || {};

        /**
         * Helper to create a labeled number input field.
         * @param {string} id - The base ID for the input element.
         * @param {string} labelText - The text for the label.
         * @param {number|string} value - The current value for the input.
         * @param {string} [placeholder=''] - Placeholder text for the input.
         * @param {string} [step='any'] - Step attribute for the number input.
         * @returns {HTMLDivElement} The div containing the label and input.
         */
        const createNumberInput = (id, labelText, value, placeholder='', step = 'any') => {
            const div = document.createElement('div');
            div.className = 'mt-2';

            const label = document.createElement('label');
            label.htmlFor = id;
            label.className = 'form-label';
            label.textContent = labelText + ':';
            div.appendChild(label);

            const input = document.createElement('input');
            input.type = 'number';
            input.id = id;
            input.name = id;
            input.value = value !== undefined ? value : '';
            input.step = step;
            input.placeholder = placeholder;
            input.className = 'form-input-base';
            div.appendChild(input);
            return div;
        };

        /**
         * Helper to create a paragraph element for hints or descriptions.
         * @param {string} text - The text content for the paragraph.
         * @returns {HTMLParagraphElement} The created paragraph element.
         */
        const createHintParagraph = (text) => {
            const p = document.createElement('p');
            p.className = 'text-xs text-gray-400 mt-1';
            p.textContent = text;
            return p;
        };

        const invertContainer = document.getElementById(`mapping-invert-container-${layerId}-${inputId}`);

        // Populate params based on the selected action
        switch (action) {
            case 'direct':
                if (invertContainer) invertContainer.style.display = 'flex'; // Show 'Invert' option for Direct mode.
                // No specific input range parameters from UI for 'direct' anymore.
                // The backend infers input range (0-1 or -1-1) based on input ID.
                // The 'invert' parameter is still handled globally via its checkbox.
                if (targetType === 'osc_channel') { 
                    paramsContainer.appendChild(createHintParagraph("Maps input to the channel range."));
                }
                break;
            case 'toggle':
                if (invertContainer) invertContainer.style.display = 'none'; // Hide 'Invert' for non-Direct modes.
                if (targetType === 'osc_channel') {
                    paramsContainer.appendChild(createHintParagraph("Toggle Min/Max."));
                } else if (targetType === 'internal_variable') {
                    paramsContainer.appendChild(createHintParagraph("Toggle 0/1.")); 
                }
                break;
            case 'set_value_from_input': 
                if (invertContainer) invertContainer.style.display = 'none';
                paramsContainer.appendChild(createNumberInput(`param-value-to-set-${layerId}-${inputId}`, 'Value to Set', currentMappingParams.value_to_set, 'e.g. 1'));
                break;
            case 'step_by_multiplier_on_trigger': 
                if (invertContainer) invertContainer.style.display = 'none';
                const stepVal = currentMappingParams.multiplier !== undefined ? currentMappingParams.multiplier : 1;
                const stepLabel = 'Step by Multiplier';
                const numberInputElement = createNumberInput(`param-step-value-${layerId}-${inputId}`, stepLabel, stepVal, 'e.g. 1 or -0.1', 'any');
                if (!numberInputElement) {
                     console.error('IMV_populateActionParameters: createNumberInput returned NULL or undefined for step_by_multiplier!');
                     return;
                }
                paramsContainer.appendChild(numberInputElement);
                if (targetType === 'osc_channel') {
                    paramsContainer.appendChild(createHintParagraph('Add/subtract the multiplier on press.'));
                } else if (targetType === 'internal_variable') {
                    paramsContainer.appendChild(createHintParagraph('Add/subtract the multiplier on press.'));
                }
                break;
            case 'reset_channel_on_trigger':
                if (invertContainer) invertContainer.style.display = 'none';
                if (targetType === 'osc_channel') {
                    paramsContainer.appendChild(createHintParagraph('Reset to channel default.'));
                }
                break;
            case 'activate_layer':
                if (invertContainer) invertContainer.style.display = 'none';
                paramsContainer.appendChild(createHintParagraph('Activate selected layer while held.'));
                break;
            case 'rate':
                if (invertContainer) invertContainer.style.display = 'none';
                // Allow high precision for rate multiplier (3 decimals). Default to 1 when unset.
                const rateDefault = (currentMappingParams.rate_multiplier !== undefined) ? currentMappingParams.rate_multiplier : 1;
                paramsContainer.appendChild(createNumberInput(`param-rate-multiplier-${layerId}-${inputId}`, 'Rate Multiplier', rateDefault, 'e.g., 1.000 or 25.500', '0.001'));
                 if (targetType === 'osc_channel') {
                    paramsContainer.appendChild(createHintParagraph("Sends input × multiplier."));
                }
                break;
            // Actions 'reset_channel', 'activate_layer' have no specific UI parameters here.
            default: // Default case to hide 'Invert' if action is not 'direct' or is empty/unknown.
                if (invertContainer) invertContainer.style.display = 'none';
                break;
        }
    }
    
    /**
     * Handles the form submission for saving an input mapping.
     * Collects data from the form, constructs the mapping object, 
     * and calls ConfigManager.updateInputMapping.
     * @param {Event} event - The form submission event.
     * @param {string} layerId - The ID of the layer.
     * @param {string} inputId - The generic ID of the input.
     */
    function _handleSaveMapping(event, layerId, inputId){
        event.preventDefault();
        const form = event.target;

        const targetType = form.querySelector(`#mapping-target-type-${layerId}-${inputId}`).value;
        let targetName;

        if (targetType === 'osc_channel') {
            const checkboxContainer = form.querySelector(`#mapping-target-name-osc-container-${layerId}-${inputId}`);
            if (checkboxContainer) {
                targetName = Array.from(checkboxContainer.querySelectorAll('input[type="checkbox"]:checked')).map(cb => cb.value);
            if (targetName.length === 0) { // If no OSC channels are selected, treat as no target.
                    targetName = null; 
            }
        } else {
                targetName = null; // Checkbox container not found for OSC, implies no target name(s).
                console.warn(`IMV_handleSaveMapping: OSC checkbox container not found for ${layerId}-${inputId}. Target name set to null.`);
        }
        } else { // For 'internal_variable' and 'layer_switch'.
            const targetNameSelect = form.querySelector(`#mapping-target-name-${layerId}-${inputId}`);
            targetName = targetNameSelect ? targetNameSelect.value : null;
        }

        let selectedAction;
        if (targetType === 'internal_variable') {
            selectedAction = 'step_by_multiplier_on_trigger'; // Only one action for internal variables.
        } else if (targetType === 'layer_switch') {
            selectedAction = 'activate_layer'; // Fixed action for layer switching
        } else {
            const actionSelect = form.querySelector(`#action-select-${layerId}-${inputId}`);
            selectedAction = actionSelect ? actionSelect.value : '';
        }
        
        const invert = form.querySelector(`#mapping-invert-${layerId}-${inputId}`).checked; // Invert checkbox state.
        const saveToAllLayers = form.querySelector(`#mapping-save-all-layers-${layerId}-${inputId}`).checked;

        if(!targetType || !targetName || !selectedAction || selectedAction === ''){
            alert("Please select Target Type, Target Name, and a valid Action.");
            return;
        }

        let mappingData = {
            target_type: targetType,
            target_name: targetName,
            action: selectedAction,
            params: {}
        };

        // Only add 'invert' param if the action is 'direct' and the checkbox is visible/relevant.
        if (selectedAction === 'direct') {
            const invertCheckbox = form.querySelector(`#mapping-invert-${layerId}-${inputId}`);
            if (invertCheckbox) { 
                mappingData.params.invert = invertCheckbox.checked;
            } else {
                mappingData.params.invert = false; // Default if somehow not found for direct mode.
                console.warn(`IMV_handleSaveMapping: Invert checkbox not found for Direct mode on ${layerId}-${inputId}. Defaulting invert to false.`);
            }
        } else {
            // For other actions, ensure 'invert' is not in params, even if it was there from a previous mapping.
            delete mappingData.params.invert;
        }

        // Populate other params based on the selected action.
        switch (selectedAction) {
            case 'rate':
                const rateMultiplierEl = form.querySelector(`#param-rate-multiplier-${layerId}-${inputId}`);
                if (rateMultiplierEl && rateMultiplierEl.value !== '') {
                    const rateVal = parseFloat(rateMultiplierEl.value);
                    if (!isNaN(rateVal)) {
                        mappingData.params.rate_multiplier = rateVal;
                    }
            } else {
                     mappingData.params.rate_multiplier = 1.0; // Default if not present or empty.
                }
                break;
            case 'step_by_multiplier_on_trigger':
                const stepValueEl = form.querySelector(`#param-step-value-${layerId}-${inputId}`);
                if (stepValueEl && stepValueEl.value !== '') {
                    const stepVal = parseFloat(stepValueEl.value);
                    if (!isNaN(stepVal)) {
                        mappingData.params.multiplier = stepVal;
                    }
                } else {
                    mappingData.params.multiplier = 1.0; // Default if not present or empty.
                }
                break;
            case 'set_value_from_input': // Formerly 'set_value_on_trigger'.
                const valueToSetEl = form.querySelector(`#param-value-to-set-${layerId}-${inputId}`);
                if (valueToSetEl && valueToSetEl.value !== '') {
                    const val = parseFloat(valueToSetEl.value);
                    if (!isNaN(val)) {
                        mappingData.params.value_to_set = val;
            }
                } else {
                    // Default or error if value_to_set is mandatory
                    console.warn(`'Value to Set' is empty for action 'set_value_from_input' on ${inputId}. Check if this is intended or needs a default.`);
                }
                break;
            // Other actions (reset_channel, activate_layer) might not have specific UI params from this section.
        }

        console.log("InputMappingView: Saving mapping data (final before send):", JSON.parse(JSON.stringify(mappingData)), "For Layer:", layerId, "Input:", inputId, "SaveAll:", saveToAllLayers);
        App.ConfigManager.updateInputMapping(layerId, inputId, mappingData, saveToAllLayers);

        // UX: Close the editor immediately to indicate save action was performed.
        const mappingConfigArea = document.getElementById(`input-mapping-config-area-${layerId.toLowerCase()}`);
        if (mappingConfigArea) {
            mappingConfigArea.innerHTML = '<p class="text-gray-400 italic">Mapping saved. Select an input to configure its mapping.</p>';
        }
        App.ConfigManager.setSelectedInput(null);
    }

    /**
     * Handles the click event for clearing an input mapping.
     * Confirms with the user and then emits an event to the backend to clear the mapping.
     * Optionally updates the UI to reflect the cleared state.
     * @param {string} layerId - The ID of the layer.
     * @param {string} inputId - The generic ID of the input.
     */
    function _handleClearMapping(layerId, inputId){
        if(confirm(`Are you sure you want to clear the mapping for '${inputId}' on Layer ${layerId}?`)){
            const saveToAllLayers = document.getElementById(`mapping-save-all-layers-${layerId}-${inputId}`)?.checked || false;
            console.log("InputMappingView: Clearing mapping:", { layerId, inputId, saveToAllLayers });
            App.SocketManager.emit('clear_input_mapping', {
                layer_id: layerId,
                input_name: inputId,
                save_to_all_layers: saveToAllLayers // Flag for backend processing.
            });
            // Optionally, clear the form right away or wait for config update to re-render.
            const mappingConfigArea = document.getElementById(`input-mapping-config-area-${layerId.toLowerCase()}`);
            if(mappingConfigArea) mappingConfigArea.innerHTML = '<p class="text-gray-400">Mapping cleared. Select an input to configure.</p>';
            App.ConfigManager.setSelectedInput(null); // Deselect the input.
        }
    }

    /**
     * Updates the visual state (mapped/unmapped, selection, type-specific classes) 
     * of all gamepad input elements (regular and motion) within a given layer 
     * based on the current configuration.
     * @param {string} layerId - The ID of the layer.
     * @param {HTMLElement} gamepadContainerElement - The DOM element containing the main gamepad visualization.
     * @param {HTMLElement} motionGridContainerElement - The DOM element containing the motion controls grid.
     */
    function _updateGamepadInputStates(layerId, gamepadContainerElement, motionGridContainerElement) {
        const currentConfig = App.ConfigManager.getConfig();
        const mappings = currentConfig.layers?.[layerId]?.input_mappings || {};

        // Update regular gamepad inputs (buttons, triggers, sticks).
        if (gamepadContainerElement) {
            gamepadContainerElement.querySelectorAll('.gamepad-input').forEach(el => {
                const inputId = el.dataset.inputId;
                el.classList.remove('unmapped', 'mapped', 'mapped-osc-channel', 'mapped-internal-variable', 'mapped-layer-switch', 'selected');

                if (mappings[inputId]) {
                    const mapping = mappings[inputId];
                    el.classList.add('mapped');
                    if (mapping.target_type === 'osc_channel') {
                        el.classList.add('mapped-osc-channel');
                    } else if (mapping.target_type === 'internal_variable') {
                        el.classList.add('mapped-internal-variable');
                    } else if (mapping.target_type === 'layer_switch') {
                        el.classList.add('mapped-layer-switch');
                    }
                } else {
                    el.classList.add('unmapped');
                }
            });
        } else {
            console.warn("_updateGamepadInputStates: gamepadContainerElement not provided or found.");
        }

        // Update motion control inputs.
        if (motionGridContainerElement) {
            motionGridContainerElement.querySelectorAll('.motion-control-item.gamepad-input').forEach(el => {
                const inputId = el.dataset.inputId;
                el.classList.remove('unmapped', 'mapped', 'mapped-osc-channel', 'mapped-internal-variable', 'mapped-layer-switch', 'selected');
                
                if (mappings[inputId]) {
                    const mapping = mappings[inputId];
                    el.classList.add('mapped');
                     if (mapping.target_type === 'osc_channel') {
                        el.classList.add('mapped-osc-channel');
                    } else if (mapping.target_type === 'internal_variable') {
                        el.classList.add('mapped-internal-variable');
                    } else if (mapping.target_type === 'layer_switch') {
                        el.classList.add('mapped-layer-switch');
                    }
                } else {
                    el.classList.add('unmapped');
                }
            });
        }

        // Re-apply selection highlight if an input is currently selected for this layer.
        const selectedInput = App.ConfigManager.getSelectedInput();

        if (selectedInput && selectedInput.layerId === layerId && selectedInput.inputId) {
            let selectedElement = null;
            if (gamepadContainerElement) {
                selectedElement = gamepadContainerElement.querySelector(`[data-input-id="${selectedInput.inputId}"]`);
            }
            if (!selectedElement && motionGridContainerElement) {
                selectedElement = motionGridContainerElement.querySelector(`[data-input-id="${selectedInput.inputId}"]`);
            }
            
            if (selectedElement) {
                selectedElement.classList.add('selected');
            }
        }
    }

    /**
     * Completely rebuilds and refreshes the gamepad visualization for a specified layer.
     * This includes re-initializing the DOM elements for the gamepad display,
     * caching these elements, updating their visual states based on current mappings,
     * and resetting the mapping configuration panel.
     * @param {string} layerId - The ID of the layer to refresh.
     */
    function _refreshGamepadForLayer(layerId) {
        console.log(`InputMappingView: Refresh layer ${layerId}`);
        _activeLayerId = layerId; // Update the module-level active layer ID.

        // Define container IDs for this layer.
        const gamepadVisContainerId = `gamepad-visualization-layer-${layerId.toLowerCase()}`;
        const motionGridContainerId = `motion-controls-grid-layer-${layerId.toLowerCase()}`;

        // Initialize/rebuild the DOM elements first.
        _initGamepadVisualization(layerId, gamepadVisContainerId);

        // Now that the DOM is fresh, cache the new visual input elements for this layer.
        _cachedLayerVisualInputs[layerId] = {}; // Clear/initialize cache for this layer.

        const gamepadContainerElement = document.getElementById(gamepadVisContainerId);
        const motionGridContainerElement = document.getElementById(motionGridContainerId);

        if (gamepadContainerElement) {
            gamepadContainerElement.querySelectorAll('.gamepad-input').forEach(el => {
                if (el.dataset.inputId) {
                    _cachedLayerVisualInputs[layerId][el.dataset.inputId] = el;
            }
            });
        } else {
            console.warn(`InputMappingView (_refreshGamepadForLayer): Gamepad container #${gamepadVisContainerId} not found after init.`);
        }

        if (motionGridContainerElement) {
            motionGridContainerElement.querySelectorAll('.gamepad-input').forEach(el => {
                if (el.dataset.inputId) { // Check if already cached from gamepadContainer to avoid overwriting.
                    if (!_cachedLayerVisualInputs[layerId][el.dataset.inputId]) {
                         _cachedLayerVisualInputs[layerId][el.dataset.inputId] = el;
                    }
                }
            });
        } else {
            // This might be normal if a layer doesn't have a dedicated motion grid container.
            }
        console.log(`InputMappingView: Cached ${Object.keys(_cachedLayerVisualInputs[layerId] || {}).length} visual inputs for layer ${layerId}.`);

        // Update states for the newly created and cached elements.
        _updateGamepadInputStates(layerId, gamepadContainerElement, motionGridContainerElement);

        App.ConfigManager.setSelectedInput(null); // Clear any previous input selection.
        const mappingConfigArea = document.getElementById(`input-mapping-config-area-${layerId.toLowerCase()}`);
        if (mappingConfigArea) {
            mappingConfigArea.innerHTML = '<p class="text-gray-400 italic">Select an input to configure its mapping.</p>';
        }
    }

    // Public API
    return {
        /**
         * Initializes the InputMappingView module.
         * Subscribes to relevant events from ConfigManager and SocketManager.
         * Fetches initial input name mappings and prepares the view for the active layer.
         * @async
         */
        init: async function() {
            console.log("InputMappingView: Initializing...");
            // _activeLayerId will be updated by showGamepadForLayer or the activeUiLayerChanged subscriber.

            if (App.ConfigManager) {
                App.ConfigManager.subscribe('configLoaded', (config) => {
                    console.log("InputMappingView: Config loaded event received. Storing config.");
                    _config = config;
                    const currentUiLayer = App.ConfigManager.getActiveUiLayerId();
                    console.log(`InputMappingView (on configLoaded): Current UI Layer is ${currentUiLayer}.`);
                    if (['A', 'B', 'C', 'D'].includes(currentUiLayer)) {
                        // If a gamepad layer is already active in UI, refresh its visualization.
                        console.log(`InputMappingView (on configLoaded): UI Layer ${currentUiLayer} is active. Refreshing gamepad.`);
                        _refreshGamepadForLayer(currentUiLayer);
                    } else {
                        console.log(`InputMappingView (on configLoaded): UI Layer ${currentUiLayer} is not a gamepad layer or not active. No initial gamepad render from here.`);
                    }
                });
                App.ConfigManager.subscribe('configUpdated', (configData) => {
                    console.log("InputMappingView: Config updated.");
                    _config = configData.new;
                     // Check if the current gamepad visualization is for the active UI layer.
                    const currentUiLayer = App.ConfigManager.getActiveUiLayerId();
                    if (_activeLayerId === currentUiLayer && ['A', 'B', 'C', 'D'].includes(_activeLayerId)) {
                        // If only the config changed (e.g., a mapping was saved) 
                        // but the layer itself wasn't re-rendered from scratch, update the input states.
                        const mainGamepadVisContainer = document.getElementById(`gamepad-visualization-layer-${_activeLayerId.toLowerCase()}`);
                        const motionGridContainer = document.getElementById(`motion-controls-grid-layer-${_activeLayerId.toLowerCase()}`);
                        _updateGamepadInputStates(_activeLayerId, mainGamepadVisContainer, motionGridContainer);
                    }
                    // If an input is selected and its mapping changed, re-render its config panel.
                    const selectedInputDetails = App.ConfigManager.getSelectedInput();
                    if(selectedInputDetails && selectedInputDetails.layerId === currentUiLayer){
                        const mappingConfigArea = document.getElementById(`input-mapping-config-area-${selectedInputDetails.layerId.toLowerCase()}`);
                        if(mappingConfigArea){
                             _renderMappingConfigPanel(mappingConfigArea, selectedInputDetails.layerId, selectedInputDetails.inputId);
                        }
                    }
                });
                App.ConfigManager.subscribe('activeUiLayerChanged', (eventData) => {
                    console.log("InputMappingView: ConfigManager activeUiLayerChanged event received", eventData);
                    _activeLayerId = eventData; // Correctly assign eventData (the newLayerId string).
                    // Refresh visualization for the new layer.
                    _refreshGamepadForLayer(_activeLayerId); 
                });
                App.ConfigManager.subscribe('selectedInputChanged', (selectedData) => {
                    if(selectedData){
                        console.log(`InputMappingView: 'selectedInputChanged' event. Input: ${selectedData.inputId}, Layer: ${selectedData.layerId}`);
                        
                        const currentUiLayer = App.ConfigManager.getActiveUiLayerId();

                        if (selectedData.layerId === currentUiLayer) { 
                            // If selected input is on the currently active UI layer, update visuals.
                            const mainGamepadVisContainer = document.getElementById(`gamepad-visualization-layer-${currentUiLayer.toLowerCase()}`);
                            const motionGridContainer = document.getElementById(`motion-controls-grid-layer-${currentUiLayer.toLowerCase()}`);
                            _updateGamepadInputStates(currentUiLayer, mainGamepadVisContainer, motionGridContainer);
                        }
                    } else {
                        console.log(`InputMappingView: 'selectedInputChanged' event. Input deselected.`);
                         // Clear selection visual from all gamepads if input is deselected globally.
                        document.querySelectorAll('.gamepad-input.selected').forEach(el => el.classList.remove('selected'));
                        // Clear mapping panel for the active layer if input was deselected.
                        const currentUiLayer = App.ConfigManager.getActiveUiLayerId();
                         if (['A', 'B', 'C', 'D'].includes(currentUiLayer)) {
                            const mappingConfigArea = document.getElementById(`input-mapping-config-area-${currentUiLayer.toLowerCase()}`);
                            if(mappingConfigArea){
                                mappingConfigArea.innerHTML = `<p class="text-gray-400 mb-2">Select an input on the gamepad to configure its mapping for Layer ${currentUiLayer}.</p>`;
                            }
                        }
                    }
                });

                // Listen for raw input updates from the server.
                if (App.SocketManager) {
                    App.SocketManager.on('raw_inputs_update', _handleRawInputUpdate);
                    console.log("InputMappingView: Subscribed to 'raw_inputs_update' from SocketManager.");
                } else {
                    console.error("InputMappingView: SocketManager not available to subscribe for raw_inputs_update.");
                }

            } else {
                console.error("InputMappingView: App.ConfigManager not available for subscription.");
            }
            
            // Initial render is primarily triggered by UIManager making a layer tab visible,
            // which then triggers 'activeUiLayerChanged'.
            console.log("InputMappingView: Initialization complete. Waiting for layer activation to render gamepad.");

            // Ensure input name map is loaded.
            await _initializeInputNameMap(); 

            // If config is already loaded by the time this init runs (e.g., on a page refresh),
            // explicitly refresh the gamepad for the initially active layer.
            if (App.ConfigManager.isConfigLoaded()) {
                _config = App.ConfigManager.getConfig();
                _activeLayerId = App.ConfigManager.getActiveUiLayerId(); 
                console.log(`InputMappingView init: Config already loaded. Initial active layer: ${_activeLayerId}. Refreshing gamepad.`);
                _refreshGamepadForLayer(_activeLayerId);
            } else {
                console.log("InputMappingView init: Config not yet loaded. Gamepad refresh will be triggered by 'configLoaded' event.");
            }

            console.log("InputMappingView initialized");
        },
    };
})(); 