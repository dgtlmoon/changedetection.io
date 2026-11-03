"""Example plugin - a fallback fetcher, used when a site blocks the normal fetch, with a longer recheck time while it is.

A fetch method that gets pages through a scraping API (any service with the small JSON contract in fetcher.py).
Pick it as a watch's fetch method, or let it take over only when needed: with "Fall back on these status codes"
set (e.g. 403), a check that gets one of those is retried once, straight away, with this fetcher. The watch is
then "under control" of the plugin for a while: its checks go straight to the fallback, at a longer recheck
time if one is set (scraping APIs cost money per page), with a note in the watch list saying so. After that
the normal fetch is tried again.

Install it with `pip install .` from the directory above this one, see example_plugins/README.md.
"""
import os
import time

from changedetectionio.plugin_api import hookimpl

# Names your settings file ({datastore}/cdio_example_fallback_fetcher.json) and the settings tab
PLUGIN_ID = 'cdio_example_fallback_fetcher'
# Fetcher names must start with 'html_', this is what's stored in a watch's 'fetch_backend'
FETCHER_NAME = 'html_example_fallback_fetcher'

# Set at startup by changedetection.io (inject_datastore_into_plugins)
datastore = None

# Watches under this plugin's control, uuid -> {'until': epoch, 'status_code': what blocked it,
# 'recheck_seconds': recheck time while under control, or 0}. Kept in memory: the scheduler asks
# recheck_seconds_override about every watch every second, so it must not read files. After a
# restart the first check tries the normal fetch again.
under_control = {}


def get_settings():
    from changedetectionio.plugin_api import load_plugin_settings
    return load_plugin_settings(datastore.datastore_path, PLUGIN_ID) if datastore else {}


def _status_codes(value):
    """'403, 429 503' -> {403, 429, 503}"""
    return {int(c) for c in str(value or '').replace(',', ' ').split() if c.isdigit()}


def _in_groups(watch, settings, datastore):
    """Blank group list = every watch, otherwise only watches in one of the named groups (tags)."""
    wanted = {g.strip().lower() for g in str(settings.get('fallback_fetcher_groups') or '').split(',') if g.strip()}
    if not wanted:
        return True
    tags = datastore.data['settings']['application'].get('tags', {})
    names = {str(tags.get(t, {}).get('title', '')).strip().lower() for t in (watch.get('tags') or [])}
    return bool(wanted & names)


def _controlled(uuid):
    """This watch's entry in under_control, if it's still under control."""
    entry = under_control.get(uuid)
    if entry and entry['until'] > time.time():
        return entry
    return None


@hookimpl
def register_content_fetcher():
    from .fetcher import fetcher
    return (FETCHER_NAME, fetcher)


@hookimpl
def select_fetch_backend(watch, datastore, backend_name, failed_fetch):
    """Use the fallback for this check when the normal fetch was blocked, or still is (under control)."""
    if backend_name == FETCHER_NAME:
        return None
    uuid = watch.get('uuid')

    if failed_fetch is None:
        # Before the fetch: under control from an earlier block? Then don't bother with the blocked fetch
        if _controlled(uuid):
            return FETCHER_NAME
        under_control.pop(uuid, None)
        return None

    # After a failed fetch: only for the status codes asked for, e.g. 403 from a bot wall
    settings = get_settings()
    codes = _status_codes(settings.get('fallback_fetcher_status_codes'))
    status_code = getattr(failed_fetch, 'status_code', None)
    if status_code not in codes or not settings.get('fallback_fetcher_url') or not _in_groups(watch, settings, datastore):
        return None
    hours = settings.get('fallback_fetcher_control_hours') or 0
    if hours > 0:
        under_control[uuid] = {'until': time.time() + hours * 3600, 'status_code': status_code,
                               'recheck_seconds': int((settings.get('fallback_fetcher_recheck_hours') or 0) * 3600)}
    return FETCHER_NAME


@hookimpl
def recheck_seconds_override(watch, datastore, seconds):
    """While a watch is under control, check it no more often than the fallback recheck time. A minimum: a watch
    that's already checked less often (say every 3 days) keeps its own recheck time."""
    entry = _controlled(watch.get('uuid'))
    if not entry or not entry['recheck_seconds']:
        return None
    return max(seconds, entry['recheck_seconds'])


@hookimpl
def watch_list_extra_text(watch):
    entry = _controlled(watch.get('uuid'))
    if not entry:
        return None
    left = max(1, round((entry['until'] - time.time()) / 3600))
    recheck = f", checked no more often than every {entry['recheck_seconds'] // 3600}h" if entry['recheck_seconds'] >= 3600 else ''
    return f"Blocked with HTTP {entry['status_code']}, using the fallback fetcher{recheck} for the next {left}h"


@hookimpl
def plugin_settings_tab():
    from wtforms import BooleanField, Form, IntegerField, StringField, validators

    class SettingsForm(Form):
        # These share the settings page form with everything else, so give them unique names
        fallback_fetcher_url = StringField('Scraping API URL', description='Pages are fetched by POSTing to this, see the plugin README')
        fallback_fetcher_key = StringField('API key', description='Sent to the API in the X-Api-Key header')
        fallback_fetcher_screenshot = BooleanField('Ask for a screenshot', default=True)
        fallback_fetcher_status_codes = StringField(
            'Fall back on these status codes',
            description='For example "403, 429". A check of a watch using any other fetch method that gets one of '
                        'these is retried once with this fetcher. Blank: only used by watches that have it as their '
                        'fetch method.')
        fallback_fetcher_groups = StringField(
            'Only for these groups', description='Group names, comma separated. Blank means all watches.')
        fallback_fetcher_control_hours = IntegerField(
            'Then keep using it for (hours)', default=24, validators=[validators.Optional(), validators.NumberRange(min=0)],
            description='After a fallback, go straight to this fetcher for this long, then try the normal fetch again. '
                        '0 tries the normal fetch first every time.')
        fallback_fetcher_recheck_hours = IntegerField(
            'Meanwhile check no more often than every (hours)', default=12, validators=[validators.Optional(), validators.NumberRange(min=0)],
            description='A minimum while the fallback is in use (scraping APIs cost per page): a watch checked less often '
                        'keeps its own recheck time. 0 keeps the normal recheck time.')

    return {'plugin_id': PLUGIN_ID, 'tab_label': 'Fallback fetcher', 'form_class': SettingsForm}


@hookimpl
def fetcher_status_icon(fetcher_name):
    """The icon next to watches using this fetcher in the watch list."""
    if fetcher_name != FETCHER_NAME:
        return None
    return {'filename': 'cdio_example_fallback_fetcher.svg', 'alt': 'Fallback fetcher', 'title': 'Fetched with the fallback fetcher',
            'group': 'plugin', 'style': 'height: 1em;'}


@hookimpl
def plugin_static_path():
    """Files in here are served at /static/plugin/<filename>."""
    return os.path.join(os.path.dirname(__file__), 'static')
