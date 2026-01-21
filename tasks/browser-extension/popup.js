/**
 * ChangeDetection.io Browser Extension - Popup Script
 *
 * Handles configuration, quick-add, and CSS selector testing functionality.
 */

// DOM Elements
const elements = {
  // Settings
  settingsForm: document.getElementById('settingsForm'),
  apiEndpoint: document.getElementById('apiEndpoint'),
  apiKey: document.getElementById('apiKey'),
  testConnection: document.getElementById('testConnection'),
  settingsMessage: document.getElementById('settingsMessage'),
  connectionStatus: document.getElementById('connectionStatus'),

  // Quick Add
  quickAddForm: document.getElementById('quickAddForm'),
  watchUrl: document.getElementById('watchUrl'),
  watchTitle: document.getElementById('watchTitle'),
  watchTag: document.getElementById('watchTag'),
  cssFilter: document.getElementById('cssFilter'),
  processor: document.getElementById('processor'),
  useCurrentUrl: document.getElementById('useCurrentUrl'),
  testSelector: document.getElementById('testSelector'),
  quickAddMessage: document.getElementById('quickAddMessage'),

  // Selector Test
  testCssSelector: document.getElementById('testCssSelector'),
  highlightSelector: document.getElementById('highlightSelector'),
  clearHighlight: document.getElementById('clearHighlight'),
  selectorResults: document.getElementById('selectorResults'),
  useSelectorForWatch: document.getElementById('useSelectorForWatch'),

  // Tabs
  tabNav: document.querySelector('.tab-nav'),
  tabContents: document.querySelectorAll('.tab-content'),
  tabButtons: document.querySelectorAll('.tab-btn')
};

// State
let currentSelector = '';
let isConfigured = false;

// ============================================
// Storage Functions
// ============================================

async function getSettings() {
  return new Promise((resolve) => {
    chrome.storage.sync.get(['apiEndpoint', 'apiKey'], (result) => {
      resolve({
        apiEndpoint: result.apiEndpoint || '',
        apiKey: result.apiKey || ''
      });
    });
  });
}

async function saveSettings(apiEndpoint, apiKey) {
  return new Promise((resolve) => {
    chrome.storage.sync.set({ apiEndpoint, apiKey }, resolve);
  });
}

// ============================================
// API Functions
// ============================================

function getApiUrl(endpoint, path) {
  // Normalize endpoint URL
  let baseUrl = endpoint.replace(/\/+$/, '');
  return `${baseUrl}/api/v1${path}`;
}

async function apiRequest(method, path, body = null) {
  const settings = await getSettings();

  if (!settings.apiEndpoint) {
    throw new Error('API endpoint not configured');
  }

  const url = getApiUrl(settings.apiEndpoint, path);
  const headers = {
    'Content-Type': 'application/json'
  };

  if (settings.apiKey) {
    headers['x-api-key'] = settings.apiKey;
  }

  const options = {
    method,
    headers
  };

  if (body) {
    options.body = JSON.stringify(body);
  }

  const response = await fetch(url, options);

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`API Error (${response.status}): ${text}`);
  }

  // Handle empty responses
  const contentType = response.headers.get('content-type');
  if (contentType && contentType.includes('application/json')) {
    return response.json();
  }

  return response.text();
}

async function testApiConnection() {
  try {
    await apiRequest('GET', '/systeminfo');
    return { success: true };
  } catch (error) {
    return { success: false, error: error.message };
  }
}

async function createWatch(watchData) {
  return apiRequest('POST', '/watch', watchData);
}

// ============================================
// UI Helper Functions
// ============================================

function showMessage(element, type, message) {
  element.className = `message ${type}`;
  element.textContent = message;
  element.style.display = 'block';

  // Auto-hide success messages
  if (type === 'success') {
    setTimeout(() => {
      element.style.display = 'none';
    }, 3000);
  }
}

function hideMessage(element) {
  element.style.display = 'none';
}

function setButtonLoading(button, loading) {
  if (loading) {
    button.disabled = true;
    button.dataset.originalText = button.textContent;
    button.innerHTML = '<span class="loading"></span>Loading...';
  } else {
    button.disabled = false;
    button.textContent = button.dataset.originalText || button.textContent;
  }
}

function updateConnectionStatus(connected) {
  isConfigured = connected;
  if (connected) {
    elements.connectionStatus.textContent = 'Connected';
    elements.connectionStatus.className = 'connection-status connected';
  } else {
    elements.connectionStatus.textContent = 'Not Connected';
    elements.connectionStatus.className = 'connection-status disconnected';
  }
}

function switchTab(tabId) {
  elements.tabContents.forEach(tab => {
    tab.classList.add('hidden');
  });
  elements.tabButtons.forEach(btn => {
    btn.classList.remove('active');
  });

  document.getElementById(tabId).classList.remove('hidden');
  document.querySelector(`[data-tab="${tabId}"]`).classList.add('active');
}

// ============================================
// Content Script Communication
// ============================================

async function getCurrentTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

async function sendToContentScript(action, data = {}) {
  const tab = await getCurrentTab();

  try {
    return await chrome.tabs.sendMessage(tab.id, { action, ...data });
  } catch (error) {
    // Content script might not be loaded yet, inject it
    await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files: ['content.js']
    });
    await chrome.scripting.insertCSS({
      target: { tabId: tab.id },
      files: ['content.css']
    });

    // Retry the message
    return chrome.tabs.sendMessage(tab.id, { action, ...data });
  }
}

// ============================================
// Event Handlers
// ============================================

// Tab Navigation
elements.tabNav.addEventListener('click', (e) => {
  if (e.target.classList.contains('tab-btn')) {
    const tabId = e.target.dataset.tab;
    switchTab(tabId);
  }
});

// Settings Form
elements.settingsForm.addEventListener('submit', async (e) => {
  e.preventDefault();

  const apiEndpoint = elements.apiEndpoint.value.trim();
  const apiKey = elements.apiKey.value.trim();

  await saveSettings(apiEndpoint, apiKey);

  // Test connection after saving
  const result = await testApiConnection();
  if (result.success) {
    showMessage(elements.settingsMessage, 'success', 'Settings saved and connection verified!');
    updateConnectionStatus(true);
  } else {
    showMessage(elements.settingsMessage, 'error', `Settings saved but connection failed: ${result.error}`);
    updateConnectionStatus(false);
  }
});

// Test Connection Button
elements.testConnection.addEventListener('click', async () => {
  setButtonLoading(elements.testConnection, true);
  hideMessage(elements.settingsMessage);

  // Use current form values (not saved ones) for testing
  const apiEndpoint = elements.apiEndpoint.value.trim();
  const apiKey = elements.apiKey.value.trim();

  // Temporarily set these for the test
  await saveSettings(apiEndpoint, apiKey);

  const result = await testApiConnection();
  setButtonLoading(elements.testConnection, false);

  if (result.success) {
    showMessage(elements.settingsMessage, 'success', 'Connection successful!');
    updateConnectionStatus(true);
  } else {
    showMessage(elements.settingsMessage, 'error', `Connection failed: ${result.error}`);
    updateConnectionStatus(false);
  }
});

// Use Current URL Button
elements.useCurrentUrl.addEventListener('click', async () => {
  const tab = await getCurrentTab();
  elements.watchUrl.value = tab.url;
  elements.watchTitle.value = tab.title || '';
});

// Test Selector Button (in Quick Add)
elements.testSelector.addEventListener('click', async () => {
  const selector = elements.cssFilter.value.trim();
  if (!selector) {
    showMessage(elements.quickAddMessage, 'error', 'Enter a CSS selector to test');
    return;
  }

  try {
    const result = await sendToContentScript('testSelector', { selector });
    if (result.count > 0) {
      showMessage(elements.quickAddMessage, 'success', `Selector matches ${result.count} element(s)`);
    } else {
      showMessage(elements.quickAddMessage, 'info', 'Selector matches 0 elements');
    }
  } catch (error) {
    showMessage(elements.quickAddMessage, 'error', `Error testing selector: ${error.message}`);
  }
});

// Quick Add Form
elements.quickAddForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  hideMessage(elements.quickAddMessage);

  if (!isConfigured) {
    showMessage(elements.quickAddMessage, 'error', 'Please configure your API settings first');
    switchTab('settingsTab');
    return;
  }

  const submitBtn = elements.quickAddForm.querySelector('button[type="submit"]');
  setButtonLoading(submitBtn, true);

  const watchData = {
    url: elements.watchUrl.value.trim(),
    title: elements.watchTitle.value.trim() || undefined,
    tag: elements.watchTag.value.trim() || undefined,
    processor: elements.processor.value
  };

  // Add CSS filter if specified
  const cssFilter = elements.cssFilter.value.trim();
  if (cssFilter) {
    watchData.include_filters = [cssFilter];
  }

  try {
    const result = await createWatch(watchData);
    showMessage(elements.quickAddMessage, 'success', 'URL added to watchlist!');

    // Clear form
    elements.watchUrl.value = '';
    elements.watchTitle.value = '';
    elements.cssFilter.value = '';
  } catch (error) {
    showMessage(elements.quickAddMessage, 'error', `Failed to add watch: ${error.message}`);
  } finally {
    setButtonLoading(submitBtn, false);
  }
});

// Highlight Selector Button
elements.highlightSelector.addEventListener('click', async () => {
  const selector = elements.testCssSelector.value.trim();
  if (!selector) {
    elements.selectorResults.innerHTML = '<p class="placeholder">Enter a CSS selector first</p>';
    return;
  }

  currentSelector = selector;
  setButtonLoading(elements.highlightSelector, true);

  try {
    const result = await sendToContentScript('highlightSelector', { selector });

    if (result.error) {
      elements.selectorResults.innerHTML = `<p style="color: #dc3545;">${result.error}</p>`;
      elements.useSelectorForWatch.disabled = true;
    } else if (result.count === 0) {
      elements.selectorResults.innerHTML = '<p style="color: #856404;">No elements match this selector</p>';
      elements.useSelectorForWatch.disabled = true;
    } else {
      let html = `<p class="match-count">${result.count} element(s) matched</p>`;

      result.elements.slice(0, 10).forEach((el, i) => {
        html += `
          <div class="match-item">
            <span class="tag-name">&lt;${el.tagName.toLowerCase()}${el.id ? ` id="${el.id}"` : ''}${el.className ? ` class="${el.className}"` : ''}&gt;</span>
            <div class="text-content">${escapeHtml(el.textContent.substring(0, 150))}${el.textContent.length > 150 ? '...' : ''}</div>
          </div>
        `;
      });

      if (result.count > 10) {
        html += `<p style="color: #666; margin-top: 8px;">...and ${result.count - 10} more</p>`;
      }

      elements.selectorResults.innerHTML = html;
      elements.useSelectorForWatch.disabled = false;
    }
  } catch (error) {
    elements.selectorResults.innerHTML = `<p style="color: #dc3545;">Error: ${error.message}</p>`;
    elements.useSelectorForWatch.disabled = true;
  } finally {
    setButtonLoading(elements.highlightSelector, false);
  }
});

// Clear Highlight Button
elements.clearHighlight.addEventListener('click', async () => {
  await sendToContentScript('clearHighlights');
  elements.selectorResults.innerHTML = '<p class="placeholder">Enter a selector and click "Highlight on Page" to see matches</p>';
  elements.useSelectorForWatch.disabled = true;
  currentSelector = '';
});

// Use Selector for Watch Button
elements.useSelectorForWatch.addEventListener('click', async () => {
  if (currentSelector) {
    elements.cssFilter.value = currentSelector;

    // Pre-fill URL if empty
    if (!elements.watchUrl.value) {
      const tab = await getCurrentTab();
      elements.watchUrl.value = tab.url;
      elements.watchTitle.value = tab.title || '';
    }

    switchTab('quickAddTab');
  }
});

// ============================================
// Utility Functions
// ============================================

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// ============================================
// Initialization
// ============================================

async function init() {
  // Load saved settings
  const settings = await getSettings();
  elements.apiEndpoint.value = settings.apiEndpoint;
  elements.apiKey.value = settings.apiKey;

  // Check connection status
  if (settings.apiEndpoint) {
    const result = await testApiConnection();
    updateConnectionStatus(result.success);

    // If connected, default to Quick Add tab
    if (result.success) {
      switchTab('quickAddTab');

      // Pre-fill current URL
      const tab = await getCurrentTab();
      elements.watchUrl.value = tab.url;
      elements.watchTitle.value = tab.title || '';
    }
  } else {
    updateConnectionStatus(false);
  }
}

// Initialize when popup loads
document.addEventListener('DOMContentLoaded', init);
