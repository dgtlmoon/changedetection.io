"""Example plugin - a fallback fetcher, used when a site blocks the normal fetch, with a longer recheck time while it is.

A fetch method that gets pages through a scraping API (any service with the small JSON contract in fetcher.py).
Pick it as a watch's fetch method, or let it take over only when needed: with "Fall back on these status codes"
set (e.g. 403), a check that gets one of those is retried once, straight away, with this fetcher. The watch is
then "under control" of the plugin for a while: its checks go straight to the fallback, at a longer recheck
time if one is set (scraping APIs cost money per page), with a note in the watch list saying so. After that
the normal fetch is tried again. "Most successful calls in 24 hours" caps what it can cost, the count is kept in
the plugin's own state file, see state.py. A "Fetch stats" page (sidebar icon) shows the usage and which watches
it has under control, with a link to its settings.

Install it with `pip install .` from the directory above this one, see example_plugins/README.md.
"""
import os
import time

from flask import Blueprint, render_template

from changedetectionio.plugin_api import hookimpl

# Names your settings file ({datastore}/cdio_example_fallback_fetcher.json) and the settings tab
PLUGIN_ID = 'cdio_example_fallback_fetcher'
# Fetcher names must start with 'html_', this is what's stored in a watch's 'fetch_backend'
FETCHER_NAME = 'html_example_fallback_fetcher'
# Among several fallback fetchers the lowest priority is tried first
DEFAULT_PRIORITY = 10

# Set at startup by changedetection.io (inject_datastore_into_plugins)
datastore = None

# Set this to fix "Meanwhile check no more often than every" for the whole install, the settings widget then
# shows it read-only. For operators who don't want it changed from the UI.
RECHECK_MINIMUM_ENV = 'EXAMPLE_FETCHER_HELLOWORLD_TIME_BETWEEN_RECHECK_MINIMUM_SECONDS'


def recheck_minimum_from_env():
    """The env var's seconds, or None when it's not set (or not a number)."""
    value = os.getenv(RECHECK_MINIMUM_ENV, '').strip()
    return int(value) if value.isdigit() else None


def recheck_minimum_seconds(settings):
    """The minimum recheck time while under control: the env var when set, otherwise the setting."""
    from changedetectionio.plugin_api import time_between_check_to_seconds
    env = recheck_minimum_from_env()
    return env if env is not None else time_between_check_to_seconds(settings.get('fallback_fetcher_recheck'))

# Watches under this plugin's control, uuid -> {'until': epoch, 'status_code': what blocked it,
# 'recheck_seconds': recheck time while under control, or 0}. Kept in memory: the scheduler asks
# recheck_seconds_override about every watch every second, so it must not read files. After a
# restart the first check tries the normal fetch again.
under_control = {}

# watch uuid -> the status code its own fetch was blocked with, during the check that's falling back now
_blocked_with = {}

# The fetch stats page. Named after the plugin, its template under templates/cdio_example_fallback_fetcher/
# so the path can't clash with a core template or another plugin's.
blueprint = Blueprint(PLUGIN_ID, __name__, template_folder='templates')


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


def _duration(seconds):
    """43200 -> '12h', 90 -> '1m', 259200 -> '3d'"""
    for unit, size in (('d', 86400), ('h', 3600), ('m', 60)):
        if seconds >= size:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


def _controlled(uuid):
    """This watch's entry in under_control, if it's still under control."""
    entry = under_control.get(uuid)
    if entry and entry['until'] > time.time():
        return entry
    return None


@blueprint.route('/')
def fetch_stats():
    from .state import WINDOW_SECONDS, calls_in_window
    settings = get_settings()
    calls = calls_in_window()
    now = time.time()
    limit = settings.get('fallback_fetcher_daily_limit') or 0
    # Calls per hour for the last 24 hours, oldest first
    per_hour = [0] * 24
    for t in calls:
        per_hour[min(23, int((now - t) // 3600))] += 1
    per_hour.reverse()
    controlled = []
    for uuid, entry in list(under_control.items()):
        watch = datastore.data['watching'].get(uuid) if datastore else None
        if watch and entry['until'] > now:
            controlled.append({'uuid': uuid, 'label': watch.label, 'status_code': entry['status_code'],
                               'left': _duration(int(entry['until'] - now)),
                               'recheck': _duration(entry['recheck_seconds']) if entry['recheck_seconds'] else None})
    return render_template(f'{PLUGIN_ID}/fetch_stats.html', calls=len(calls), limit=limit, per_hour=per_hour,
                           peak=max(per_hour) or 1, controlled=controlled, plugin_id=PLUGIN_ID,
                           free_in=_duration(int(calls[len(calls) - limit] + WINDOW_SECONDS - now) + 1)
                           if limit and len(calls) >= limit else None,
                           configured=bool(settings.get('fallback_fetcher_url')),
                           status_codes=settings.get('fallback_fetcher_status_codes') or '')


@hookimpl
def register_blueprints(datastore):
    """The fetch stats page, behind the same login as the rest of the UI."""
    return {'blueprint': blueprint, 'url_prefix': '/fallback-fetcher'}


@hookimpl
def register_sidebar_items(datastore):
    """An icon in the left sidebar for the fetch stats page. Called on every page render, so stay in memory."""
    return {
        'label': 'Fetch stats',
        'title': 'Fallback fetcher - usage and watches it has taken over',
        'endpoint': f'{PLUGIN_ID}.fetch_stats',
        'icon': 'bar-chart-2',
        'active_prefix': f'{PLUGIN_ID}.',
    }


@hookimpl
def register_content_fetcher():
    from .fetcher import fetcher
    return (FETCHER_NAME, fetcher)


def over_daily_limit(settings):
    """Seconds until the next call is allowed, when the daily limit is used up, otherwise 0. In memory, cheap."""
    from .state import WINDOW_SECONDS, calls_in_window
    limit = settings.get('fallback_fetcher_daily_limit') or 0
    calls = calls_in_window()
    if limit and len(calls) >= limit:
        return max(1, int(calls[len(calls) - limit] + WINDOW_SECONDS - time.time()) + 1)
    return 0


def take_control(uuid, settings):
    """Called by the fetcher once a fallback fetch worked: from now on this watch is ours for a while."""
    status_code = _blocked_with.pop(uuid, None)
    hours = settings.get('fallback_fetcher_control_hours') or 0
    if status_code and hours > 0 and not _controlled(uuid):
        under_control[uuid] = {'until': time.time() + hours * 3600, 'status_code': status_code,
                               'recheck_seconds': recheck_minimum_seconds(settings)}


@hookimpl
def select_fetch_backend(watch, datastore, backend_name, failed_fetch, tried):
    """Offer the fallback for this check when the normal fetch was blocked, or still is (under control).
    Core tries the offers of all fallback plugins in priority order, so another one can come before or after."""
    if backend_name == FETCHER_NAME or FETCHER_NAME in tried:
        return None
    uuid = watch.get('uuid')
    settings = get_settings()
    priority = settings.get('fallback_fetcher_priority')
    offer = {'backend': FETCHER_NAME, 'priority': DEFAULT_PRIORITY if priority is None else priority}
    # Over the daily limit: don't offer, so the next fallback in line gets the attempt instead
    if not settings.get('fallback_fetcher_url') or over_daily_limit(settings):
        return None

    if failed_fetch is None:
        # Before the fetch, a new check: under control from an earlier block? Then skip the blocked fetch
        _blocked_with.pop(uuid, None)
        if _controlled(uuid):
            return offer
        under_control.pop(uuid, None)
        return None

    if len(tried) == 1:
        # The watch's own fetch failed: only for the status codes asked for, e.g. 403 from a bot wall
        status_code = getattr(failed_fetch, 'status_code', None)
        if status_code not in _status_codes(settings.get('fallback_fetcher_status_codes')) \
                or not _in_groups(watch, settings, datastore):
            return None
        # Remembered even if another fallback comes first, so we can still step in if that one fails too
        _blocked_with[uuid] = status_code
        return offer

    # Further down the chain: a fallback that came before us failed (its error, not the site's, is failed_fetch).
    # Offer if the watch's own fetch was blocked in a way we fall back for
    return offer if uuid in _blocked_with else None


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
    recheck = f", checked no more often than every {_duration(entry['recheck_seconds'])}" if entry['recheck_seconds'] else ''
    return f"Blocked with HTTP {entry['status_code']}, using the fallback fetcher{recheck} for the next {left}h"


@hookimpl
def plugin_settings_tab():
    from wtforms import BooleanField, Form, FormField, IntegerField, StringField, validators
    from changedetectionio.plugin_api import TimeBetweenCheckForm
    from .state import calls_in_window

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
        fallback_fetcher_priority = IntegerField(
            'Priority', default=DEFAULT_PRIORITY, validators=[validators.Optional()],
            description='When several fallback fetchers are installed, the lowest number is tried first, and the '
                        'next one when it fails or is over its daily limit.')
        fallback_fetcher_groups = StringField(
            'Only for these groups', description='Group names, comma separated. Blank means all watches.')
        fallback_fetcher_control_hours = IntegerField(
            'Then keep using it for (hours)', default=24, validators=[validators.Optional(), validators.NumberRange(min=0)],
            description='After a fallback, go straight to this fetcher for this long, then try the normal fetch again. '
                        '0 tries the normal fetch first every time.')
        # The same weeks/days/hours/minutes/seconds widget as the recheck time everywhere else
        fallback_fetcher_recheck = FormField(
            TimeBetweenCheckForm, label='Meanwhile check no more often than every', default={'hours': 12},
            render_kw={'class': 'time-check-widget'},
            description='A minimum while the fallback is in use (scraping APIs cost per page): a watch checked less '
                        'often keeps its own recheck time. Empty keeps the normal recheck time.')
        fallback_fetcher_daily_limit = IntegerField(
            'Most successful calls in 24 hours', default=0, validators=[validators.Optional(), validators.NumberRange(min=0)],
            description=f'Over this, checks that need the fallback fail with an error instead of calling the API. '
                        f'0 for no limit. Used in the last 24 hours: {len(calls_in_window())}.')

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            env = recheck_minimum_from_env()
            if env is not None:
                # Fixed by the env var: show its seconds, read-only. Disabled inputs aren't submitted, which is
                # fine, the env var wins over whatever is saved anyway.
                widget = self.fallback_fetcher_recheck
                for part in widget.form:
                    part.data = env if part.short_name == 'seconds' else None
                    part.render_kw = {'disabled': True, 'readonly': True}
                widget.description = f'Set to {env} seconds by the {RECHECK_MINIMUM_ENV} environment variable.'

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
