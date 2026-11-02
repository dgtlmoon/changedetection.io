"""
Example plugin - an extra browser fetcher that gets pages through its own API.

Configure it under Settings > "Example browser fetcher", then pick "Example browser fetcher" as a
watch's fetch method. Install it with `pip install .` from the directory above this one, see
example_plugins/README.md. It is not active until installed (or registered).
"""
import os

from changedetectionio.plugin_api import hookimpl

# Names your settings file ({datastore}/cdio_example_browser_fetcher.json) and the settings tab
PLUGIN_ID = 'cdio_example_browser_fetcher'
# Fetcher names must start with 'html_', this is what's stored in a watch's 'fetch_backend'
FETCHER_NAME = 'html_example_browser_fetcher'

# Set at startup by changedetection.io (inject_datastore_into_plugins), the fetcher reads its
# settings with it
datastore = None


@hookimpl
def register_content_fetcher():
    from .fetcher import fetcher
    return (FETCHER_NAME, fetcher)


@hookimpl
def plugin_settings_tab():
    from wtforms import Form, StringField

    class SettingsForm(Form):
        # These share the settings page form with everything else, so give them unique names
        example_browser_fetcher_url = StringField(
            'API URL',
            description='Use {url} where the page URL goes, for example https://api.example.com/fetch?url={url}')
        example_browser_fetcher_key = StringField(
            'API key', description='Sent to the API in the X-Api-Key header')

    return {'plugin_id': PLUGIN_ID, 'tab_label': 'Example browser fetcher', 'form_class': SettingsForm}


@hookimpl
def fetcher_status_icon(fetcher_name):
    """The icon next to watches using this fetcher in the watch list."""
    if fetcher_name != FETCHER_NAME:
        return None
    return {'filename': 'cdio_example_browser_fetcher.svg', 'alt': 'Example browser fetcher', 'title': 'Fetched with the example browser fetcher',
            'group': 'plugin', 'style': 'height: 1em;'}


@hookimpl
def plugin_static_path():
    """Files in here are served at /static/plugin/<filename>."""
    return os.path.join(os.path.dirname(__file__), 'static')
