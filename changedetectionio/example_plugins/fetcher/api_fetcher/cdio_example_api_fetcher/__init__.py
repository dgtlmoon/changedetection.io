"""
Example plugin - a content fetcher that gets pages through a scraping API service instead of directly.

Configure it under Settings > "Scraping API (example)", then pick "Scraping API (example plugin)" as a
watch's fetch method. Install it with `pip install .` from the directory above this one, see
example_plugins/README.md. It is not active until installed (or registered).
"""
import os

from changedetectionio.plugin_api import hookimpl

# Names your settings file ({datastore}/cdio_example_api_fetcher.json) and the settings tab
PLUGIN_ID = 'cdio_example_api_fetcher'
# Fetcher names must start with 'html_', this is what's stored in a watch's 'fetch_backend'
FETCHER_NAME = 'html_example_api_fetcher'

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
        example_api_fetcher_url = StringField(
            'API URL',
            description='Use {url} where the page URL goes, for example https://api.example.com/fetch?url={url}')
        example_api_fetcher_key = StringField(
            'API key', description='Sent to the API in the X-Api-Key header')

    return {'plugin_id': PLUGIN_ID, 'tab_label': 'Scraping API (example)', 'form_class': SettingsForm}


@hookimpl
def fetcher_status_icon(fetcher_name):
    """The icon next to watches using this fetcher in the watch list."""
    if fetcher_name != FETCHER_NAME:
        return None
    return {'filename': 'cdio_example_api_fetcher.svg', 'alt': 'Scraping API', 'title': 'Fetched through the scraping API',
            'group': 'plugin', 'style': 'height: 1em;'}


@hookimpl
def plugin_static_path():
    """Files in here are served at /static/plugin/<filename>."""
    return os.path.join(os.path.dirname(__file__), 'static')
