"""Pure helpers behind the PWA blueprint.

Kept free of Flask request state so they can be unit tested directly - the routes and the
watch list pass the request values in.
"""

import os

DEFAULT_NAME = 'ChangeDetection.io'
DESCRIPTION = 'Web page change detection and monitoring'

# Set to force the mobile-install UI on (or off) regardless of the detected scheme
HTTPS_OVERRIDE_ENV = 'FORCE_MOBILE_HTTPS_STYLE_MANIFEST'


def https_mode(is_secure):
    """Should this instance offer the phone-install UI?

    A PWA can only be installed over HTTPS, so anything that invites someone to install
    (today the Settings QR code, later an Install button) has to be hidden otherwise - it
    would send them to a page with no Install option and no explanation why.

    Detection is request.is_secure, which reads X-Forwarded-Proto via ProxyFix - but only
    when USE_X_SETTINGS is set. Terminating TLS at a proxy that doesn't send that header, or
    running without USE_X_SETTINGS, makes a perfectly installable instance look like plain
    http, so FORCE_MOBILE_HTTPS_STYLE_MANIFEST overrides the guess in either direction.
    """
    forced = os.getenv(HTTPS_OVERRIDE_ENV, '').strip()
    if forced:
        from changedetectionio import strtobool
        return bool(strtobool(forced))

    return bool(is_secure)


def instance_names(forwarded_prefix='', script_root=''):
    """Work out what this instance should be called on a home screen.

    Co-tenanted instances (same host, different sub-path, as in
    https://example.com/my-instance/) install as separate PWAs with separate icons and
    separate Android share-sheet entries. Sharing one name makes them indistinguishable at
    the point of use, so allow an override and otherwise derive something human out of the
    sub-path: /my-instance -> "My Instance".

    Returns (name, short_name).
    """
    name = os.getenv('PWA_NAME', '').strip()
    if not name:
        prefix = (forwarded_prefix or script_root or '').strip('/')
        name = prefix.replace('-', ' ').replace('_', ' ').title() if prefix else DEFAULT_NAME

    short_name = os.getenv('PWA_SHORT_NAME', '').strip()
    if not short_name:
        # Launcher labels ellipsise somewhere around 12 characters
        short_name = name if len(name) <= 12 else name.split(' ')[0][:12]

    return name, short_name


MAX_URL_LENGTH = 2000


def pwa_preset_url(args):
    r"""Pull the URL out of an Android Web Share Target hand-off.

    The manifest's share_target action is the watch list itself, so a share arrives as
    GET /?pwa_preset_url=... and all this does is prefill the quick-add form's URL field -
    the processor radios and LLM intent box already sitting under it then do the rest. No
    watch is created here; that still takes the form's POST, so a share can't add anything
    on its own.

    The url param is only populated when the sharing app sets Intent.EXTRA_TEXT to a bare
    link. Plenty of Android apps instead share prose with the link buried in it ("Check this
    out https://..."), which arrives as text/title, so fall back to digging it out.

    Extraction is linkify-it-py (already a dependency, also used by the notification
    handler) rather than a regex, purely because it is better at this one job - the real
    URL validation happens on the form's POST, not here. A naive https?://\S+ swallows the
    full stop in "...have a look at https://example.com/page." and the closing bracket in
    "(see https://example.com/x)", while still breaking
    https://en.wikipedia.org/wiki/Foo_(bar) where the bracket belongs to the URL. A URL
    prefilled with a trailing full stop is a failed first share.
    """
    explicit = (args.get('pwa_preset_url') or '').strip()

    # An app that populated the url field gave us a real URL, so take it verbatim - the
    # linkifier would trim a trailing character that may well be significant here.
    if explicit.lower().startswith(('http://', 'https://')):
        return explicit[:MAX_URL_LENGTH]

    from linkify_it import LinkifyIt

    linkify = LinkifyIt()
    for candidate in (explicit, args.get('pwa_preset_text'), args.get('pwa_preset_title')):
        if not candidate:
            continue
        for match in linkify.match(candidate) or []:
            # The linkifier also resolves mailto:, ftp: and protocol-relative //host links.
            # Prefilling any of those is just noise in a box that only ever wants a web page.
            if match.url.lower().startswith(('http://', 'https://')):
                return match.url[:MAX_URL_LENGTH]

    return ''


SHARE_ARGS = ('pwa_preset_url', 'pwa_preset_text', 'pwa_preset_title')


def is_share(args):
    """True when this request came in through the share sheet rather than the app icon.

    start_url and share_target.action are the same URL ("./"), so the only thing telling a
    share apart from a normal launch is the presence of these params. Tapping the home
    screen icon must not produce share-related UI.
    """
    return any(args.get(k) for k in SHARE_ARGS)
