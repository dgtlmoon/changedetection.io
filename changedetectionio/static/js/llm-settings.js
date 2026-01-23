/**
 * LLM Settings JavaScript (US-026)
 * Handles dynamic model dropdown population and test extraction functionality.
 */

(function() {
    'use strict';

    // Model configurations for each provider
    const PROVIDER_MODELS = {
        'openai': [
            { value: 'gpt-4o-mini', label: 'GPT-4o Mini (Recommended - Cheapest)' },
            { value: 'gpt-4o', label: 'GPT-4o (Best Quality)' },
            { value: 'gpt-4-turbo', label: 'GPT-4 Turbo' },
            { value: 'gpt-4', label: 'GPT-4' },
            { value: 'gpt-3.5-turbo', label: 'GPT-3.5 Turbo' },
            { value: 'o1-mini', label: 'o1-mini (Reasoning)' },
            { value: 'o1', label: 'o1 (Advanced Reasoning)' }
        ],
        'anthropic': [
            { value: 'claude-3-5-haiku-20241022', label: 'Claude 3.5 Haiku (Recommended - Fastest)' },
            { value: 'claude-3-5-sonnet-20241022', label: 'Claude 3.5 Sonnet (Best Quality)' },
            { value: 'claude-sonnet-4-20250514', label: 'Claude Sonnet 4' },
            { value: 'claude-3-opus-20240229', label: 'Claude 3 Opus (Most Capable)' },
            { value: 'claude-3-sonnet-20240229', label: 'Claude 3 Sonnet' },
            { value: 'claude-3-haiku-20240307', label: 'Claude 3 Haiku' }
        ],
        'ollama': [
            { value: 'llama3.2', label: 'Llama 3.2 (Recommended)' },
            { value: 'llama3.1', label: 'Llama 3.1' },
            { value: 'mistral', label: 'Mistral' },
            { value: 'mixtral', label: 'Mixtral' },
            { value: 'gemma2', label: 'Gemma 2' },
            { value: 'phi3', label: 'Phi-3' },
            { value: 'qwen2.5', label: 'Qwen 2.5' },
            { value: 'deepseek-coder-v2', label: 'DeepSeek Coder V2' }
        ]
    };

    // Default models for each provider
    const DEFAULT_MODELS = {
        'openai': 'gpt-4o-mini',
        'anthropic': 'claude-3-5-haiku-20241022',
        'ollama': 'llama3.2'
    };

    /**
     * Initialize LLM settings functionality
     */
    function init() {
        const providerSelect = document.getElementById('application-llm_extraction-provider');
        const modelSelect = document.getElementById('application-llm_extraction-model');
        const apiKeyGroup = document.getElementById('llm-api-key-group');
        const testButton = document.getElementById('llm-test-button');
        const enabledCheckbox = document.getElementById('application-llm_extraction-enabled');

        if (!providerSelect || !modelSelect) {
            return; // Not on the settings page
        }

        // Store current model value for restoration if needed
        const currentModelValue = modelSelect.value;

        // Update models when provider changes
        providerSelect.addEventListener('change', function() {
            updateModels(this.value, modelSelect, apiKeyGroup);
        });

        // Initial update based on current provider
        const currentProvider = providerSelect.value;
        if (currentProvider) {
            updateModels(currentProvider, modelSelect, apiKeyGroup, currentModelValue);
        }

        // Toggle settings visibility based on enabled checkbox
        if (enabledCheckbox) {
            toggleSettingsVisibility(enabledCheckbox.checked);
            enabledCheckbox.addEventListener('change', function() {
                toggleSettingsVisibility(this.checked);
            });
        }

        // Test extraction button
        if (testButton) {
            testButton.addEventListener('click', handleTestExtraction);
        }
    }

    /**
     * Update the model dropdown based on selected provider
     */
    function updateModels(provider, modelSelect, apiKeyGroup, preserveValue) {
        // Clear current options
        modelSelect.innerHTML = '';

        // Add placeholder option
        const placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.textContent = provider ? '-- Select Model --' : '-- Select Provider First --';
        modelSelect.appendChild(placeholder);

        // Show/hide API key field based on provider
        if (apiKeyGroup) {
            if (provider === 'ollama') {
                apiKeyGroup.style.display = 'none';
            } else {
                apiKeyGroup.style.display = '';
            }
        }

        // Add models for the selected provider
        const models = PROVIDER_MODELS[provider] || [];
        models.forEach(function(model) {
            const option = document.createElement('option');
            option.value = model.value;
            option.textContent = model.label;
            modelSelect.appendChild(option);
        });

        // Restore previous value if it exists in new options, otherwise use default
        if (preserveValue && models.some(m => m.value === preserveValue)) {
            modelSelect.value = preserveValue;
        } else if (provider && DEFAULT_MODELS[provider]) {
            modelSelect.value = DEFAULT_MODELS[provider];
        }
    }

    /**
     * Toggle visibility of settings sections based on enabled state
     */
    function toggleSettingsVisibility(enabled) {
        const providerSettings = document.getElementById('llm-provider-settings');
        const advancedSettings = document.getElementById('llm-advanced-settings');
        const testSection = document.getElementById('llm-test-section');

        if (providerSettings) providerSettings.style.opacity = enabled ? '1' : '0.5';
        if (advancedSettings) advancedSettings.style.opacity = enabled ? '1' : '0.5';
        if (testSection) testSection.style.opacity = enabled ? '1' : '0.5';
    }

    /**
     * Handle test extraction button click
     */
    function handleTestExtraction() {
        const testUrl = document.getElementById('llm-test-url');
        const testButton = document.getElementById('llm-test-button');
        const resultDiv = document.getElementById('llm-test-result');
        const outputPre = document.getElementById('llm-test-output');

        if (!testUrl || !testUrl.value.trim()) {
            alert('Please enter a test URL');
            return;
        }

        // Get CSRF token
        const csrfToken = document.querySelector('input[name="csrf_token"]');
        if (!csrfToken) {
            alert('CSRF token not found');
            return;
        }

        // Disable button and show loading
        testButton.disabled = true;
        testButton.textContent = 'Testing...';
        resultDiv.style.display = 'block';
        outputPre.textContent = 'Fetching page and running AI extraction...';

        // Get current form values (unsaved settings)
        const provider = document.getElementById('application-llm_extraction-provider').value;
        const model = document.getElementById('application-llm_extraction-model').value;
        const apiKey = document.getElementById('application-llm_extraction-api_key').value;
        const apiBaseUrl = document.getElementById('application-llm_extraction-api_base_url').value;
        const promptTemplate = document.getElementById('application-llm_extraction-prompt_template').value;
        const timeout = document.getElementById('application-llm_extraction-timeout').value;

        // Make the test request
        fetch('/settings/test-llm-extraction', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken.value
            },
            body: JSON.stringify({
                url: testUrl.value.trim(),
                provider: provider,
                model: model,
                api_key: apiKey,
                api_base_url: apiBaseUrl,
                prompt_template: promptTemplate,
                timeout: parseInt(timeout) || 30
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                outputPre.textContent = JSON.stringify(data.result, null, 2);
                if (data.cost) {
                    outputPre.textContent += '\n\n--- Cost ---\n' +
                        'Input tokens: ' + data.cost.input_tokens + '\n' +
                        'Output tokens: ' + data.cost.output_tokens + '\n' +
                        'Cost: $' + data.cost.cost_usd;
                }
            } else {
                outputPre.textContent = 'Error: ' + (data.error || 'Unknown error');
            }
        })
        .catch(error => {
            outputPre.textContent = 'Request failed: ' + error.message;
        })
        .finally(() => {
            testButton.disabled = false;
            testButton.textContent = 'Test Extraction';
        });
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
