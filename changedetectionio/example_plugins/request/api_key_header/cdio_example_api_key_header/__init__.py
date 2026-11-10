"""
Example plugin - an API key header for each watch, set under "Show advanced options" in the edit page's Request tab.

The key is saved in the watch's data dir as cdio_example_api_key_header.json, never in the watch itself, so it
isn't in the watch's JSON, the API or backups of the watch settings. The page never shows it again: leave the
field empty to keep it, tick "Remove the key" to drop it.

The same three hooks are all an OAuth 2.0, HMAC signing or rotating-token plugin needs, fetch the token in
fetch_request_alter (through request['proxy_url'], with asyncio.to_thread for blocking calls).

Install it with `pip install .` from the directory above this one, see example_plugins/README.md.
"""
from wtforms import BooleanField, Form, PasswordField, StringField, validators

from changedetectionio.plugin_api import hookimpl, load_watch_plugin_settings

PLUGIN_ID = 'cdio_example_api_key_header'


class ApiKeyHeaderForm(Form):
    # Every validator must pass on an empty form, the Request tab isn't shown for every fetcher
    header_name = StringField('API key header', [validators.Optional(), validators.Length(max=200),
                                                 validators.Regexp(r'^[A-Za-z0-9-]+$', message='Letters, digits and - only')],
                              default='X-Api-Key')
    # Never sent back to the page
    api_key = PasswordField('API key', [validators.Optional(), validators.Length(max=2000)])
    remove_key = BooleanField('Remove the key', default=False)


def _on_save(watch, data, stored):
    """Called with the form's data and what is saved now, returns what to save."""
    if data.get('remove_key'):
        api_key = ''
    else:
        # An empty field keeps the stored key, the page never shows it
        api_key = data.get('api_key') or stored.get('api_key', '')
    return {'header_name': data.get('header_name') or 'X-Api-Key', 'api_key': api_key}


@hookimpl
def ui_edit_request_settings(watch, datastore):
    return {
        'plugin_id': PLUGIN_ID,
        'form_class': ApiKeyHeaderForm,
        'template': 'cdio_example_api_key_header/edit.html',
        'on_save': _on_save,
    }


@hookimpl
def watch_settings_files(watch):
    # "Clear history" keeps the key
    return f"{PLUGIN_ID}.json"


@hookimpl
def fetch_request_alter(watch, datastore, request):
    settings = load_watch_plugin_settings(watch, PLUGIN_ID)
    # A header the user set on the watch wins
    if settings.get('api_key') and settings.get('header_name') not in request['headers']:
        request['headers'][settings['header_name']] = settings['api_key']
