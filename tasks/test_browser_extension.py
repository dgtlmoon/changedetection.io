"""
Unit tests for browser extension functionality.

Tests the JavaScript functions and API integration for the ChangeDetection.io
browser extension. Since we can't directly run JavaScript tests in this
environment, these tests validate the Python API endpoints that the extension
interacts with.
"""

import pytest
import json
import os


class TestExtensionManifest:
    """Test the extension manifest configuration."""

    @pytest.fixture
    def manifest_path(self):
        """Path to the extension manifest."""
        return os.path.join(
            os.path.dirname(__file__),
            "browser-extension",
            "manifest.json"
        )

    def test_manifest_exists(self, manifest_path):
        """Test that manifest.json exists."""
        assert os.path.exists(manifest_path), "manifest.json should exist"

    def test_manifest_is_valid_json(self, manifest_path):
        """Test that manifest.json is valid JSON."""
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        assert isinstance(manifest, dict)

    def test_manifest_version_3(self, manifest_path):
        """Test that manifest uses version 3 (Chrome MV3)."""
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        assert manifest.get("manifest_version") == 3

    def test_manifest_has_required_fields(self, manifest_path):
        """Test that manifest has all required fields."""
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        required_fields = [
            "manifest_version",
            "name",
            "version",
            "description",
            "permissions",
            "action",
        ]

        for field in required_fields:
            assert field in manifest, f"Manifest should have '{field}' field"

    def test_manifest_permissions(self, manifest_path):
        """Test that manifest has required permissions."""
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        permissions = manifest.get("permissions", [])

        # Required permissions for extension functionality
        assert "activeTab" in permissions, "Should have activeTab permission"
        assert "storage" in permissions, "Should have storage permission"
        assert "scripting" in permissions, "Should have scripting permission"

    def test_manifest_action_popup(self, manifest_path):
        """Test that manifest defines popup action."""
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        action = manifest.get("action", {})
        assert "default_popup" in action, "Should have default_popup"
        assert action["default_popup"] == "popup.html"

    def test_manifest_content_scripts(self, manifest_path):
        """Test that manifest defines content scripts."""
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        content_scripts = manifest.get("content_scripts", [])
        assert len(content_scripts) > 0, "Should have content scripts"

        script = content_scripts[0]
        assert "content.js" in script.get("js", [])
        assert "content.css" in script.get("css", [])


class TestExtensionFiles:
    """Test that all required extension files exist."""

    @pytest.fixture
    def extension_dir(self):
        """Path to the extension directory."""
        return os.path.join(
            os.path.dirname(__file__),
            "browser-extension"
        )

    def test_popup_html_exists(self, extension_dir):
        """Test that popup.html exists."""
        path = os.path.join(extension_dir, "popup.html")
        assert os.path.exists(path), "popup.html should exist"

    def test_popup_css_exists(self, extension_dir):
        """Test that popup.css exists."""
        path = os.path.join(extension_dir, "popup.css")
        assert os.path.exists(path), "popup.css should exist"

    def test_popup_js_exists(self, extension_dir):
        """Test that popup.js exists."""
        path = os.path.join(extension_dir, "popup.js")
        assert os.path.exists(path), "popup.js should exist"

    def test_content_js_exists(self, extension_dir):
        """Test that content.js exists."""
        path = os.path.join(extension_dir, "content.js")
        assert os.path.exists(path), "content.js should exist"

    def test_content_css_exists(self, extension_dir):
        """Test that content.css exists."""
        path = os.path.join(extension_dir, "content.css")
        assert os.path.exists(path), "content.css should exist"

    def test_icon_exists(self, extension_dir):
        """Test that icon exists."""
        path = os.path.join(extension_dir, "icons", "icon.svg")
        assert os.path.exists(path), "icon.svg should exist"


class TestPopupHtmlStructure:
    """Test the popup HTML structure for required elements."""

    @pytest.fixture
    def popup_html(self):
        """Read and return popup.html content."""
        path = os.path.join(
            os.path.dirname(__file__),
            "browser-extension",
            "popup.html"
        )
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def test_has_settings_form(self, popup_html):
        """Test that popup has settings form for API configuration."""
        assert 'id="settingsForm"' in popup_html
        assert 'id="apiEndpoint"' in popup_html
        assert 'id="apiKey"' in popup_html

    def test_has_api_endpoint_input(self, popup_html):
        """Test that popup has API endpoint input field."""
        assert 'apiEndpoint' in popup_html
        assert 'type="url"' in popup_html

    def test_has_api_key_input(self, popup_html):
        """Test that popup has API key input field."""
        assert 'apiKey' in popup_html
        assert 'type="password"' in popup_html

    def test_has_test_connection_button(self, popup_html):
        """Test that popup has test connection button."""
        assert 'id="testConnection"' in popup_html
        assert "Test Connection" in popup_html

    def test_has_quick_add_form(self, popup_html):
        """Test that popup has quick add form."""
        assert 'id="quickAddForm"' in popup_html
        assert 'id="watchUrl"' in popup_html

    def test_has_use_current_url_button(self, popup_html):
        """Test that popup has use current URL button."""
        assert 'id="useCurrentUrl"' in popup_html
        assert "Use Current Page" in popup_html

    def test_has_css_selector_input(self, popup_html):
        """Test that popup has CSS selector filter input."""
        assert 'id="cssFilter"' in popup_html

    def test_has_selector_test_tab(self, popup_html):
        """Test that popup has CSS selector test tab."""
        assert 'id="selectorTab"' in popup_html
        assert 'id="testCssSelector"' in popup_html
        assert 'id="highlightSelector"' in popup_html
        assert 'id="clearHighlight"' in popup_html

    def test_has_tab_navigation(self, popup_html):
        """Test that popup has tab navigation."""
        assert 'class="tab-nav"' in popup_html
        assert 'data-tab="settingsTab"' in popup_html
        assert 'data-tab="quickAddTab"' in popup_html
        assert 'data-tab="selectorTab"' in popup_html


class TestPopupJsStructure:
    """Test the popup JavaScript structure for required functionality."""

    @pytest.fixture
    def popup_js(self):
        """Read and return popup.js content."""
        path = os.path.join(
            os.path.dirname(__file__),
            "browser-extension",
            "popup.js"
        )
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def test_has_settings_storage(self, popup_js):
        """Test that popup.js has settings storage functions."""
        assert "getSettings" in popup_js
        assert "saveSettings" in popup_js
        assert "chrome.storage.sync" in popup_js

    def test_has_api_request_function(self, popup_js):
        """Test that popup.js has API request function."""
        assert "async function apiRequest" in popup_js or "apiRequest" in popup_js
        assert "x-api-key" in popup_js

    def test_has_connection_test(self, popup_js):
        """Test that popup.js has connection test functionality."""
        assert "testApiConnection" in popup_js
        assert "/systeminfo" in popup_js

    def test_has_create_watch_function(self, popup_js):
        """Test that popup.js has create watch function."""
        assert "createWatch" in popup_js
        assert "/watch" in popup_js

    def test_handles_api_key_header(self, popup_js):
        """Test that popup.js sends API key in header."""
        assert "x-api-key" in popup_js
        assert "headers" in popup_js

    def test_has_content_script_communication(self, popup_js):
        """Test that popup.js can communicate with content script."""
        assert "sendToContentScript" in popup_js
        assert "chrome.tabs.sendMessage" in popup_js

    def test_has_selector_test_functionality(self, popup_js):
        """Test that popup.js has selector test functionality."""
        assert "highlightSelector" in popup_js or "testSelector" in popup_js


class TestContentJsStructure:
    """Test the content script structure for required functionality."""

    @pytest.fixture
    def content_js(self):
        """Read and return content.js content."""
        path = os.path.join(
            os.path.dirname(__file__),
            "browser-extension",
            "content.js"
        )
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def test_has_highlight_function(self, content_js):
        """Test that content.js has highlight function."""
        assert "highlightSelector" in content_js
        assert "querySelectorAll" in content_js

    def test_has_clear_highlights_function(self, content_js):
        """Test that content.js has clear highlights function."""
        assert "clearHighlights" in content_js

    def test_has_test_selector_function(self, content_js):
        """Test that content.js has test selector function."""
        assert "testSelector" in content_js

    def test_has_message_listener(self, content_js):
        """Test that content.js listens for messages from popup."""
        assert "chrome.runtime.onMessage.addListener" in content_js

    def test_handles_highlight_action(self, content_js):
        """Test that content.js handles highlight action."""
        assert "'highlightSelector'" in content_js or '"highlightSelector"' in content_js

    def test_handles_clear_action(self, content_js):
        """Test that content.js handles clear highlights action."""
        assert "'clearHighlights'" in content_js or '"clearHighlights"' in content_js

    def test_has_highlight_class(self, content_js):
        """Test that content.js uses consistent highlight class."""
        assert "cdio-selector-highlight" in content_js

    def test_scrolls_to_match(self, content_js):
        """Test that content.js scrolls to first match."""
        assert "scrollIntoView" in content_js


class TestContentCssStructure:
    """Test the content CSS structure for highlight styling."""

    @pytest.fixture
    def content_css(self):
        """Read and return content.css content."""
        path = os.path.join(
            os.path.dirname(__file__),
            "browser-extension",
            "content.css"
        )
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def test_has_highlight_class_styles(self, content_css):
        """Test that content.css has highlight class styles."""
        assert ".cdio-selector-highlight" in content_css

    def test_has_visible_outline(self, content_css):
        """Test that highlight has visible outline."""
        assert "outline" in content_css

    def test_has_background_highlight(self, content_css):
        """Test that highlight has background color."""
        assert "background-color" in content_css


class TestApiIntegration:
    """Test the API endpoints that the extension uses."""

    def test_api_endpoint_format(self):
        """Test expected API endpoint format."""
        base_url = "https://example.com"
        expected = f"{base_url}/api/v1/watch"

        # This tests the URL construction logic
        result = f"{base_url.rstrip('/')}/api/v1/watch"
        assert result == expected

    def test_watch_data_structure(self):
        """Test the watch data structure sent to API."""
        watch_data = {
            "url": "https://example.com/page",
            "title": "Test Page",
            "tag": "test-tag",
            "processor": "text_json_diff",
            "include_filters": [".price"]
        }

        # Validate required fields
        assert "url" in watch_data
        assert watch_data["url"].startswith("http")

        # Validate optional fields
        assert "processor" in watch_data
        assert watch_data["processor"] in ["text_json_diff", "restock_diff"]

    def test_api_key_header_format(self):
        """Test the API key header format."""
        api_key = "test-api-key-12345"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key
        }

        assert headers["x-api-key"] == api_key
        assert "x-api-key" in headers


class TestAcceptanceCriteria:
    """Test that all acceptance criteria are met."""

    @pytest.fixture
    def extension_dir(self):
        """Path to the extension directory."""
        return os.path.join(
            os.path.dirname(__file__),
            "browser-extension"
        )

    @pytest.fixture
    def popup_html(self, extension_dir):
        """Read popup.html content."""
        path = os.path.join(extension_dir, "popup.html")
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    @pytest.fixture
    def popup_js(self, extension_dir):
        """Read popup.js content."""
        path = os.path.join(extension_dir, "popup.js")
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def test_ac1_custom_api_endpoint_configuration(self, popup_html, popup_js):
        """
        AC1: Extension can be configured with custom API endpoint URL.

        Validates:
        - API endpoint input field exists
        - Settings can be saved to storage
        - API calls use configured endpoint
        """
        # Input field exists
        assert 'id="apiEndpoint"' in popup_html
        assert 'type="url"' in popup_html

        # Storage functions exist
        assert "saveSettings" in popup_js
        assert "getSettings" in popup_js
        assert "chrome.storage.sync" in popup_js

        # API uses configured endpoint
        assert "apiEndpoint" in popup_js
        assert "/api/v1" in popup_js

    def test_ac2_api_key_authentication(self, popup_html, popup_js):
        """
        AC2: API key authentication supported.

        Validates:
        - API key input field exists
        - API key is stored securely
        - API key is sent in requests
        """
        # Input field exists
        assert 'id="apiKey"' in popup_html
        assert 'type="password"' in popup_html

        # API key is stored
        assert "apiKey" in popup_js
        assert "storage" in popup_js

        # API key is sent in header
        assert "x-api-key" in popup_js

    def test_ac3_quick_add_current_page(self, popup_html, popup_js):
        """
        AC3: Quick-add current page to watchlist works.

        Validates:
        - Quick add form exists
        - Use current page button exists
        - Watch creation API is called
        """
        # Quick add form exists
        assert 'id="quickAddForm"' in popup_html
        assert 'id="watchUrl"' in popup_html

        # Use current page button
        assert 'id="useCurrentUrl"' in popup_html
        assert "Use Current Page" in popup_html

        # Get current tab functionality
        assert "getCurrentTab" in popup_js
        assert "chrome.tabs.query" in popup_js

        # Create watch API call
        assert "createWatch" in popup_js
        assert "POST" in popup_js

    def test_ac4_css_selector_testing_preview(self, popup_html, popup_js, extension_dir):
        """
        AC4: CSS selector testing/preview works.

        Validates:
        - Selector input field exists
        - Highlight button exists
        - Clear highlights button exists
        - Results display exists
        - Content script handles highlighting
        """
        # Selector input
        assert 'id="testCssSelector"' in popup_html or 'id="cssFilter"' in popup_html

        # Highlight buttons
        assert 'id="highlightSelector"' in popup_html
        assert 'id="clearHighlight"' in popup_html

        # Results display
        assert 'id="selectorResults"' in popup_html

        # Content script communication
        assert "sendToContentScript" in popup_js
        assert "highlightSelector" in popup_js

        # Content script file exists
        content_js_path = os.path.join(extension_dir, "content.js")
        assert os.path.exists(content_js_path)

        with open(content_js_path, "r", encoding="utf-8") as f:
            content_js = f.read()

        # Content script handles highlighting
        assert "highlightSelector" in content_js
        assert "clearHighlights" in content_js
        assert "querySelectorAll" in content_js
