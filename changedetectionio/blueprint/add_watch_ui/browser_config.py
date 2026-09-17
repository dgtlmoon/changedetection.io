"""Which content fetchers can drive the Add-Watch live preview / visual selector.

Single source of truth for "can this browser render a live preview": the Add-Watch
browser list, the /snapshot endpoint and the submit-time form validator all resolve
through here, so the UI can never offer - and the server can never accept - a fetcher
that is unable to produce what the visual selector needs.

The preview drives an interactive browser session, so a usable browser needs
`supports_browser_steps` *as well as* screenshots and xpath element data. That third flag
is what rules out Selenium/WebDriver: it can screenshot during a normal check, but it
cannot drive the interactive session the preview needs (it would quietly connect to
PLAYWRIGHT_DRIVER_URL instead, which is not the browser the user picked). It also rules
out settings.requests extra_browsers, which are WebDriver connection URLs, so they are not
offered here.

A "browser" here is a *selector*, not necessarily an engine name: it can be a saved
browser config id (see model/browser_config.py) as well as a built-in engine or 'system'.
Everything resolves to a concrete engine through resolve_backend() before capabilities are
read, so a named config is judged by the engine it is built on.
"""

from loguru import logger

SYSTEM_DEFAULT = 'system'

# Every flag a fetcher must set to be usable for the Add-Watch live preview.
REQUIRED_CAPABILITIES = (
    'supports_browser_steps',
    'supports_screenshots',
    'supports_xpath_element_data',
)


def is_visual_capable(fetch_backend, datastore):
    """True when this browser choice can render the Add-Watch live preview.

    An unknown name - including anything a client made up - resolves to no fetcher
    class and so to all-False capabilities, so it can never pass. That is what makes
    the posted value safe without any string filtering of our own.

    Reads the flags off the class the same way Watch.fetcher_supports_screenshots does,
    rather than via pluggy_interface.get_fetcher_capabilities(): that logs every lookup
    at INFO, and this runs for the whole browser list on any page carrying the quick-add
    form. Plugin fetchers are registered as module attributes, so they resolve here too.
    """
    from changedetectionio import content_fetchers
    from changedetectionio.content_fetchers.base import FetcherCapabilities

    name = resolve_backend(fetch_backend, datastore)

    caps = FetcherCapabilities.from_fetcher(getattr(content_fetchers, name, None))
    missing = [flag for flag in REQUIRED_CAPABILITIES if not getattr(caps, flag, False)]
    logger.debug(f"Add-watch browser '{fetch_backend or SYSTEM_DEFAULT}' -> '{name}': "
                 f"{', '.join(f'{k}={v}' for k, v in caps.model_dump().items())} - "
                 f"{'usable for live preview' if not missing else 'not offered, missing ' + ', '.join(missing)}")
    return not missing


def resolve_backend(fetch_backend, datastore):
    """The concrete engine name behind a choice, so 'system' and saved browser configs can
    be acted on.

    Needed because launching a browser looks the name up as a fetcher class: handing it
    'system' would skip a fetcher that launches its own browser (CloakBrowser) and fall
    through to the CDP endpoint instead, and handing it a browser-config id would resolve
    to nothing at all.
    """
    selected = fetch_backend or SYSTEM_DEFAULT
    if selected == SYSTEM_DEFAULT:
        # The global default is itself a selector - it can name a saved config, so keep resolving.
        selected = datastore.data['settings']['application'].get('fetch_backend') or 'html_requests'

    # A saved browser config is judged (and launched) by the engine it is built on.
    entry, engine, _config = datastore.browser_config_store.engine_and_config(selected)
    if entry:
        return engine

    if selected.startswith('extra_browser_'):
        # settings.requests extra_browsers are WebDriver connection URLs
        return 'html_webdriver'

    # A built-in engine name - or something invented by a client, which resolves to no fetcher
    # class and therefore to no capabilities, so it can never pass is_visual_capable().
    return selected


def list_visual_browser_choices(datastore):
    """(value, label) for every browser that can drive the visual selector.

    Candidates are the same ones the watch edit picker offers - the built-in engines plus
    the user's saved browser configs (model/browser_config.py) - minus 'system', which is
    offered separately by radio_choices() because it needs its own explanatory label.

    is_visual_capable() logs each candidate's capabilities as it goes, so a user wondering
    why their browser isn't in the list can see the missing flag at debug level.
    """
    from changedetectionio.model.browser_config import list_watch_browser_choices

    # A saved browser config deliberately shares its id with the built-in engine it was
    # migrated from (see update_35), so the candidate list can name the same browser twice -
    # keep the later (saved) label, which is the one the user can rename.
    candidates = {value: label for value, label in list_watch_browser_choices(datastore)
                  if value != SYSTEM_DEFAULT}
    choices = [(value, str(label)) for value, label in candidates.items()
               if is_visual_capable(value, datastore)]
    logger.debug(f"Add-watch browsers offered for the live preview: "
                 f"{[value for value, _label in choices] or 'none'}")
    return choices


def has_visual_browser(datastore):
    """True when at least one installed browser can render a live preview.

    Gates the whole Add-Watch page (sidebar link + the route itself): without one there
    is nothing for the visual selector to work on, so the page can only fail.
    """
    return bool(list_visual_browser_choices(datastore))


def default_visual_browser(datastore):
    """Which browser the Add-Watch page should start on.

    'system' when the global default happens to be capable (so the new watch keeps
    following the system setting), otherwise the first capable browser, and None when
    there is nothing usable at all.
    """
    if is_visual_capable(SYSTEM_DEFAULT, datastore):
        return SYSTEM_DEFAULT
    choices = list_visual_browser_choices(datastore)
    return choices[0][0] if choices else None


def system_default_description(datastore):
    """Label for whatever browser 'system' currently points at (engine or saved config)."""
    from changedetectionio import content_fetchers

    system_backend = datastore.data['settings']['application'].get('fetch_backend') or 'html_requests'
    entry = datastore.browser_config_store.get(system_backend)
    if entry:
        return entry.get('label') or system_backend
    return str(dict(content_fetchers.available_fetchers()).get(system_backend, system_backend))


def radio_choices(datastore):
    """(value, label) for the Add-Watch browser radio list, system default first.

    'System settings default' is always listed - with the reason in its own label when
    the global default cannot render a preview, because greying it out explains why it
    is unavailable where silently dropping it does not. Which entries are unusable is
    reported separately by unusable_values(); WTForms cannot carry per-option render_kw
    through a RadioField, so the disabled attribute is applied when rendering.
    """
    from flask_babel import gettext

    described = system_default_description(datastore)

    if is_visual_capable(SYSTEM_DEFAULT, datastore):
        system_label = gettext('System settings default (%(browser)s)', browser=described)
    else:
        system_label = gettext('System settings default (%(browser)s - no live preview)', browser=described)

    return [(SYSTEM_DEFAULT, system_label)] + list_visual_browser_choices(datastore)


def unusable_values(datastore):
    """Values that are listed for explanation only and must render disabled."""
    return set() if is_visual_capable(SYSTEM_DEFAULT, datastore) else {SYSTEM_DEFAULT}
