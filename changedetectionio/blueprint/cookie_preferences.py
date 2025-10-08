from typing import Dict, Any
from flask import request


class PreferenceManager:
    """
    Manages user preferences with cookie persistence.

    Handles reading from cookies, overriding with URL query parameters,
    and setting cookies when preferences are updated.
    """

    def __init__(self, preferences_config: Dict[str, Dict[str, Any]], cookie_scope: str = 'path'):
        """
        Initialize the preference manager.

        Args:
            preferences_config: Dict defining preferences with their defaults and types
                               e.g., {'diff_type': {'default': 'diffLines', 'type': 'value'}}
            cookie_scope: 'path' for current path only, 'global' for entire application
        """
        self.config = preferences_config
        self.cookie_scope = cookie_scope
        self.preferences = {}
        self.cookies_updated = False

    def load_preferences(self) -> Dict[str, Any]:
        """
        Load preferences from cookies and override with URL query parameters.

        URL query parameters act as temporary overrides but don't update cookies.

        Returns:
            Dict containing current preference values
        """
        for key, config in self.config.items():
            # Read from cookie first (or use default)
            if config['type'] == 'bool':
                if key in request.cookies:
                    # Cookie exists, use its value
                    self.preferences[key] = request.cookies.get(key) == 'on'
                else:
                    # No cookie, use configured default
                    self.preferences[key] = config['default']
            else:
                self.preferences[key] = request.cookies.get(key, config['default'])

            # URL query parameters override (but don't update cookies)
            if key in request.args:
                if config['type'] == 'bool':
                    self.preferences[key] = request.args.get(key) == 'on'
                else:
                    self.preferences[key] = request.args.get(key, config['default'])

        return self.preferences

    def load_from_form(self) -> Dict[str, Any]:
        """
        Load preferences from POST form data and mark for cookie updates.

        For checkboxes: absence in form.data means unchecked = False.

        Returns:
            Dict containing preference values from form
        """
        self.cookies_updated = True

        for key, config in self.config.items():
            if config['type'] == 'bool':
                # Checkbox: present = on, absent = off
                self.preferences[key] = key in request.form and request.form.get(key) == 'on'
            else:
                # Value field: get from form or use default
                self.preferences[key] = request.form.get(key, config['default'])

        return self.preferences

    def apply_cookies_to_response(self, response, max_age: int = 365 * 24 * 60 * 60):
        """
        Apply cookies to the response if preferences were updated.

        Args:
            response: Flask response object
            max_age: Cookie expiration time in seconds (default: 1 year)

        Returns:
            Modified response object
        """
        if not self.cookies_updated:
            return response

        cookie_path = request.path if self.cookie_scope == 'path' else '/'

        for key, value in self.preferences.items():
            cookie_value = 'on' if value is True else ('off' if value is False else value)
            response.set_cookie(key, cookie_value, max_age=max_age, path=cookie_path)

        return response
