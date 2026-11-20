"""
Turn Apprise's own service descriptions into small form descriptions, and form values back into an
Apprise URL, for the notification setup widget.

Apprise describes every service (plugins.details()) in a shape that's made for describing URLs, not
forms: templates spell out every combination of optional URL parts, `schema` is listed as a field,
list fields come as a pair (the list plus one item of it, linked by `group`), and a dozen generic
?query options sit on every service. describe_service() boils that down to the fields a person
actually fills in.

The URL itself is always written by Apprise: build_url() hands the values to the service's own
class and asks it for .url(), so we never assemble Apprise URL syntax ourselves.

The one exception is "Custom POST/GET/PUT/DELETE…", changedetection.io's own plain HTTP request
handlers (apprise_plugin/custom_handlers.py, get:// post:// put:// ... with an https "s" variant of each).
Apprise can't describe those (they're just "{schema}://"), so that entry is written here by hand: a
normal http(s):// URL plus a method, turned into post:// posts:// etc.

Nothing is cached: one service's details cost well under a millisecond, and keeping all of them
would hold ~1.4MB per instance.
"""
import re

# ?query options every service has. Hidden from the form: they're transport tuning, and `format`
# is chosen by changedetection.io's own notification format setting.
GENERIC_ARGS = {'verify', 'redirect', 'rto', 'cto', 'overflow', 'format', 'emojis', 'store', 'tz',
                'retry', 'wait', 'optional'}

# The hand-written entry for our own HTTP request handlers, see _describe_custom_http()
CUSTOM_HTTP = 'custom-http'
CUSTOM_HTTP_METHODS = ('POST', 'GET', 'PUT', 'PATCH', 'DELETE', 'HEAD')

# A list field typed into one input box, "a@x.com, b@y.com" or one per line
_LIST_SPLIT = re.compile(r'[,\n]+')


def _service_name(plugin):
    """Apprise's name for the service, except plain SMTP e-mail, which is "Custom e-mail" so it isn't
    mistaken for the ready-made e-mail box (NOTIFICATION_MAIL_BUTTON_PREFIX)."""
    plain, secure = _protocols(plugin)
    if 'mailto' in plain + secure:
        from flask_babel import gettext
        return gettext('Custom e-mail')
    return str(plugin.service_name)


def _manager():
    from apprise.manager_plugins import NotificationManager
    return NotificationManager()


def _is_listed(plugin):
    """Real Apprise services only: enabled, named, and not one of our custom get:// post:// handlers."""
    if not getattr(plugin, 'enabled', True) or not getattr(plugin, 'service_name', None):
        return False
    return getattr(plugin, 'category', None) != 'custom'


def _protocols(plugin):
    def as_tuple(value):
        if not value:
            return ()
        return (value,) if isinstance(value, str) else tuple(value)
    return as_tuple(getattr(plugin, 'protocol', None)), as_tuple(getattr(plugin, 'secure_protocol', None))


def _lang(lang):
    """Context manager that makes Apprise's labels come out in `lang` (Apprise ships its own translations)."""
    import contextlib
    if not lang:
        return contextlib.nullcontext()
    import apprise
    return apprise.Apprise().locale.lang_at(str(lang).split('_')[0])


def list_services(q=None):
    """[{'schema', 'name', 'setup_url'}] sorted by name, optionally filtered by a search string."""
    q = (q or '').strip().lower()
    services = []
    for plugin in _manager().plugins():
        if not _is_listed(plugin):
            continue
        plain, secure = _protocols(plugin)
        schema = (secure or plain or (None,))[0]
        if not schema:
            continue
        name = _service_name(plugin)
        if q and q not in name.lower() and not any(q in p for p in plain + secure):
            continue
        services.append({'schema': schema, 'name': name, 'setup_url': getattr(plugin, 'setup_url', None)})

    custom = _custom_http_entry()
    if not q or q in custom['name'].lower() or any(k.startswith(q) for k in custom['keywords']):
        services.append(custom)
    return sorted(services, key=lambda s: s['name'].lower())


def _plugin_for(schema):
    schema = (schema or '').strip().lower()
    if not schema:
        return None
    try:
        plugin = _manager()[schema]
    except KeyError:
        return None
    return plugin if plugin and _is_listed(plugin) else None


def _field(key, spec, list_label=None):
    """One form field from an Apprise token/arg spec."""
    apprise_type = spec.get('type', 'string')
    base, _, sub = apprise_type.partition(':')
    if base == 'list':
        kind = 'list'
    elif base == 'choice':
        kind = 'select'
    elif base == 'bool':
        kind = 'checkbox'
    elif base in ('int', 'float'):
        kind = 'number'
    elif base == 'email':
        kind = 'email'
    else:
        kind = 'password' if spec.get('private') else 'text'

    field = {
        'key': key,
        'label': str(list_label or spec.get('name') or key),
        'type': kind,
        'required': bool(spec.get('required')),
    }
    if spec.get('default') not in (None, ''):
        field['default'] = spec['default']
    if kind == 'select':
        field['values'] = [str(v) for v in spec.get('values') or ()]
    if kind == 'number':
        for limit in ('min', 'max'):
            if spec.get(limit) is not None:
                field[limit] = spec[limit]
    return field


_TEMPLATE_TOKEN = re.compile(r'\{(\w+)\}')


def _required_sets(details):
    """What has to be filled in, read from the service's URL templates.

    Apprise's `required` on a token means "required in the URL forms that use it", not "always
    required": Slack marks both its webhook tokens (token_a/b/c) and its bot token (access_token) as
    required, and lists templates for each, because they are two ways in. So a token is only always
    required when every template has it; the rest are alternatives.

    Returns (always, alternatives):
        always: set of token keys every URL form needs
        alternatives: [set, ...] of further keys, one of these sets has to be complete as well.
                      Empty when nothing more is needed (one URL form needs only `always`).
    """
    tokens = details.get('tokens', {})
    required = {key for key, spec in tokens.items() if spec.get('required') and key != 'schema'}
    templates = details.get('templates') or ()
    if not templates:
        return required, []

    # A template names the list ({targets}) or one item of it ({target_channel}), both mean the list
    member_of = {member: key for key, spec in tokens.items() for member in spec.get('group') or ()}
    needs = []
    for template in templates:
        used = {member_of.get(token, token) for token in _TEMPLATE_TOKEN.findall(template)}
        needs.append(frozenset(used & required))
    # Only the smallest combinations count: {a} makes {a, b} pointless as an alternative
    minimal = [n for n in set(needs) if not any(other < n for other in needs)]
    always = set(frozenset.intersection(*minimal)) if minimal else set()
    alternatives = [set(n - always) for n in minimal]
    if not all(alternatives):
        alternatives = []
    return always, sorted(alternatives, key=lambda a: (len(a), sorted(a)))


def describe_service(schema, lang=None):
    """The form for one service, or None if the schema isn't a listed service.

    {'schema', 'name', 'setup_url', 'secure_toggle': bool,
     'fields': [...], 'options': [...], 'kwargs': [{'key', 'label', 'prefix'}],
     'one_of': [[field key, ...], ...]}

    `one_of` is only there when the service can be set up in more than one way: one of these groups
    of fields has to be filled in (Slack: the bot token, or the three webhook tokens). Those fields
    are not `required` on their own.
    """
    if schema == CUSTOM_HTTP:
        return _describe_custom_http()
    plugin = _plugin_for(schema)
    if not plugin:
        return None
    from apprise import plugins

    plain, secure = _protocols(plugin)
    with _lang(lang):
        details = plugins.details(plugin)
        name = _service_name(plugin)
        tokens = details.get('tokens', {})

        # Single-item tokens that belong to a list token (target_user -> targets) aren't shown on their
        # own, but their name labels the list ("Target Chat ID" reads better than "Targets")
        member_of = {}
        for key, spec in tokens.items():
            for member in spec.get('group') or ():
                member_of[member] = key

        always, alternatives = _required_sets(details)

        fields = []
        for key, spec in tokens.items():
            if key == 'schema' or key in member_of:
                continue
            list_label = None
            accepts = None
            if spec.get('group'):
                # `group` is a set, so take the names in the order Apprise declares the tokens
                names = [str(tokens[m]['name']) for m in tokens if m in spec['group'] and tokens[m].get('name')]
                if len(names) == 1:
                    list_label = names[0]
                elif names:
                    # Several kinds of item (Slack: channel, user, e-mail, ID): no single one of them
                    # describes the box, so it keeps the list's own name and says what it takes
                    accepts = names
            field = _field(key, spec, list_label=list_label)
            field['required'] = key in always
            if accepts:
                field['accepts'] = accepts
            fields.append(field)
        # Required first, then the alternative ways in, otherwise Apprise's order
        in_alternative = set().union(*alternatives) if alternatives else set()
        fields.sort(key=lambda f: 0 if f['required'] else 1 if f['key'] in in_alternative else 2)

        options = [_field(key, spec) for key, spec in details.get('args', {}).items()
                   if key not in GENERIC_ARGS and key not in tokens and 'alias_of' not in spec]

        kwargs = [{'key': key, 'label': str(spec.get('name') or key), 'prefix': spec.get('prefix')}
                  for key, spec in details.get('kwargs', {}).items() if spec.get('prefix')]

    return {
        'schema': (secure or plain)[0],
        'name': name,
        'setup_url': getattr(plugin, 'setup_url', None),
        'secure_toggle': bool(plain and secure),
        'fields': fields,
        'options': options,
        'kwargs': kwargs,
        **({'one_of': [[f['key'] for f in fields if f['key'] in group] for group in alternatives]}
           if alternatives else {}),
    }


def _coerce(field, value):
    """A submitted form value as the Python value Apprise's class expects, or None to leave it out."""
    if field['type'] == 'checkbox':
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ('1', 'true', 'yes', 'on')
    if isinstance(value, str):
        value = value.strip()
    if value in (None, ''):
        return None
    if field['type'] == 'list':
        items = value if isinstance(value, list) else _LIST_SPLIT.split(value)
        items = [str(i).strip() for i in items if str(i).strip()]
        return items or None
    if field['type'] == 'number':
        try:
            return int(value)
        except (TypeError, ValueError):
            return float(value)
    return value


def _normalise(value):
    value = getattr(value, 'value', value)  # some defaults are enums
    value = str(value).strip().lower()
    return {'true': 'yes', 'false': 'no', '1': 'yes', '0': 'no'}.get(value, value)


def _strip_default_args(url, plugin):
    """Drop ?query options that only repeat their default, .url() writes every one of them out.

    The generic options are always dropped: the form never sets them, so Apprise falls back to the
    same values when they're missing, and `format` must come from changedetection.io's own format
    setting. Segments that stay are kept exactly as Apprise wrote them.
    """
    from urllib.parse import unquote_plus
    from apprise import plugins

    args = plugins.details(plugin).get('args', {})
    base, sep, query = url.partition('?')
    if not sep:
        return url
    kept = []
    for segment in query.split('&'):
        key, _, value = segment.partition('=')
        key, value = unquote_plus(key), unquote_plus(value)
        if key in GENERIC_ARGS:
            continue
        default = args.get(key, {}).get('default')
        if default is not None and _normalise(value) == _normalise(default):
            continue
        kept.append(segment)
    return base + ('?' + '&'.join(kept) if kept else '')


def build_url(schema, values=None, secure=True, extra=None):
    """Build an Apprise URL from form values.

    Args:
        schema: the service's schema, as returned by describe_service()
        values: {field or option key: value}
        secure: use the secure scheme, for services that have both (json / jsons)
        extra: {'headers': {'X-Thing': 'v'}, ...} for the free-form key/value prefixes

    Returns:
        {'url': str, 'url_masked': str} or {'error': str}
    """
    if schema == CUSTOM_HTTP:
        return _build_custom_http(values or {}, extra or {})
    plugin = _plugin_for(schema)
    if not plugin:
        return {'error': f"Unknown notification service '{schema}'"}

    form = describe_service(schema)
    from apprise import plugins
    details = plugins.details(plugin)
    specs = {**details.get('args', {}), **details.get('tokens', {})}

    kwargs = {}
    values = values or {}
    for field in form['fields'] + form['options']:
        if field['key'] not in values:
            continue
        value = _coerce(field, values[field['key']])
        if value is None:
            continue
        kwargs[specs[field['key']].get('map_to', field['key'])] = value

    missing = [f['label'] for f in form['fields']
               if f['required'] and specs[f['key']].get('map_to', f['key']) not in kwargs]
    if missing:
        return {'error': f"Required: {', '.join(missing)}", 'missing': missing}

    # More than one way to set the service up: one of the groups has to be complete
    one_of = form.get('one_of')
    if one_of and not any(all(specs[key].get('map_to', key) in kwargs for key in group) for group in one_of):
        labels = {f['key']: f['label'] for f in form['fields']}
        choices = [[labels[key] for key in group] for group in one_of]
        return {'error': 'Required: ' + ' / '.join(' + '.join(c) for c in choices), 'one_of': choices}

    # Some services (Telegram) take the target list as a required argument, even when it may be empty
    for field in form['fields']:
        if field['type'] == 'list':
            kwargs.setdefault(specs[field['key']].get('map_to', field['key']), [])

    for kw in form['kwargs']:
        pairs = (extra or {}).get(kw['key'])
        if pairs:
            kwargs[kw['key']] = {str(k).strip(): str(v) for k, v in pairs.items() if str(k).strip()}

    if form['secure_toggle']:
        kwargs['secure'] = bool(secure)

    try:
        instance = plugin(**kwargs)
        url = instance.url()
        masked = instance.url(privacy=True)
    except Exception as e:
        return {'error': str(e) or type(e).__name__}

    url = _strip_default_args(url, plugin)
    masked = _strip_default_args(masked, plugin)

    # The URL has to survive being read back the way it will be at send time
    import apprise
    if not apprise.Apprise.instantiate(url):
        return {'error': f"{form['name']}: some required values are missing or invalid"}

    return {'url': url, 'url_masked': masked}


# ---- "Custom POST/GET/PUT/DELETE…", changedetection.io's own HTTP request handlers ----

def _custom_http_entry():
    from flask_babel import gettext
    return {
        'schema': CUSTOM_HTTP,
        'name': gettext('Custom POST/GET/PUT/DELETE…'),
        # No "How do I get these?" link, there's nothing to go and fetch, it's the user's own endpoint
        'setup_url': None,
        # Shown instead of a scheme in the service list
        'hint': 'webhook / API',
        # Searching any of these finds this entry first
        'keywords': [m.lower() for m in CUSTOM_HTTP_METHODS] + ['webhook', 'api', 'http'],
    }


def _describe_custom_http():
    from flask_babel import gettext
    entry = _custom_http_entry()
    return {
        'schema': CUSTOM_HTTP,
        'name': entry['name'],
        'setup_url': entry['setup_url'],
        'secure_toggle': False,  # follows the URL's own http:// or https://
        'fields': [
            {'key': 'url', 'label': gettext('URL'), 'type': 'text', 'required': True,
             'placeholder': 'https://api.example.com/hook'},
            {'key': 'method', 'label': gettext('Method'), 'type': 'select', 'required': True,
             'values': list(CUSTOM_HTTP_METHODS), 'default': 'POST'},
            # Username and password on a line of their own
            {'key': 'user', 'label': gettext('Username'), 'type': 'text', 'required': False, 'new_row': True},
            {'key': 'password', 'label': gettext('Password'), 'type': 'password', 'required': False},
        ],
        'options': [],
        'kwargs': [
            {'key': 'headers', 'label': gettext('HTTP headers'), 'prefix': '+'},
            {'key': 'params', 'label': gettext('Query parameters'), 'prefix': ''},
        ],
    }


def _build_custom_http(values, extra):
    """https://api.example.com/hook + POST -> posts://api.example.com/hook, headers as ?+Name=Value
    and query parameters as plain ?name=value, the way custom_handlers.py reads them back."""
    from urllib.parse import quote, urlencode, urlsplit
    from flask_babel import gettext

    url = str(values.get('url') or '').strip()
    method = str(values.get('method') or 'POST').strip().upper()
    if not url:
        return {'error': f"{gettext('Required')}: {gettext('URL')}", 'missing': [gettext('URL')]}
    if method not in CUSTOM_HTTP_METHODS:
        return {'error': f"Unknown method '{method}'"}

    parts = urlsplit(url)
    if parts.scheme.lower() not in ('http', 'https') or not parts.hostname:
        return {'error': gettext('The URL must start with http:// or https://')}

    schema = method.lower() + ('s' if parts.scheme.lower() == 'https' else '')
    host = parts.hostname + (f':{parts.port}' if parts.port else '')

    def assemble(password_shown):
        user = str(values.get('user') or '').strip() or parts.username
        password = str(values.get('password') or '') or parts.password
        auth = ''
        if user:
            auth = quote(user, safe='')
            if password:
                auth += ':' + (quote(password, safe='') if password_shown else '****')
            auth += '@'
        query = [parts.query] if parts.query else []
        headers = {k: v for k, v in (extra.get('headers') or {}).items() if str(k).strip()}
        params = {k: v for k, v in (extra.get('params') or {}).items() if str(k).strip()}
        if params:
            query.append(urlencode(params))
        if headers:
            # Lowercase names: custom_handlers._get_params() only recognises a lowercase "+name" as a header and
            # would otherwise also send it as a query parameter. It title-cases them again before sending.
            # Values are often credentials (Authorization: Bearer ...), hidden in the preview.
            query.append('&'.join(f"+{quote(str(k).strip().lower(), safe='')}="
                                  f"{quote(str(v), safe='') if password_shown else '****'}"
                                  for k, v in headers.items()))
        return f"{schema}://{auth}{host}{parts.path or '/'}" + ('?' + '&'.join(query) if query else '')

    full = assemble(True)

    # Registers get:// post:// ... with Apprise, they're otherwise only added on first use
    import apprise
    import changedetectionio.notification.apprise_plugin.custom_handlers  # noqa: F401
    if not apprise.Apprise.instantiate(full):
        return {'error': gettext('The URL must start with http:// or https://')}
    return {'url': full, 'url_masked': assemble(False)}
