"""
Browser steps as a watch stores them, [{operation, selector, optional_value}]: which operations there are, what each
one takes, and the checks that a list of them will run. Kept apart from browser_steps/browser_steps.py (which runs
them, and imports the fetchers) so anything that only needs to check or describe steps (the MCP server, the API)
stays light.
"""
import re

# Two flags per operation, for the edit form's JS and for validate_steps(): does it take a "Selector", a "Value"
# 0- off, 1- on
browser_step_ui_config = {'Choose one': '0 0',
                          #                 'Check checkbox': '1 0',
                          #                 'Click button containing text': '0 1',
                          #                 'Scroll to bottom': '0 0',
                          #                 'Scroll to element': '1 0',
                          #                 'Scroll to top': '0 0',
                          #                 'Switch to iFrame by index number': '0 1'
                          #                 'Uncheck checkbox': '1 0',
                          # @todo
                          'Check checkbox': '1 0',
                          'Click X,Y': '0 1',
                          'Click element if exists': '1 0',
                          'Click element': '1 0',
                          'Click element containing text': '0 1',
                          'Click element containing text if exists': '0 1',
                          'Enter text in field': '1 1',
                          'Execute JS': '0 1',
#                          'Extract text and use as filter': '1 0',
                          'Goto site': '0 0',
                          'Goto URL': '0 1',
                          'Make all child elements visible': '1 0',
                          'Press Enter': '0 0',
                          'Select by label': '1 1',
                          '<select> by option text': '1 1',
                          'Scroll down': '0 0',
                          'Uncheck checkbox': '1 0',
                          'Wait for seconds': '0 1',
                          'Wait for text': '0 1',
                          'Wait for text in element': '1 1',
                          'Remove elements': '1 0',
                          #                          'Press Page Down': '0 0',
                          #                          'Press Page Up': '0 0',
                          # weird bug, come back to it later
                          }

TEXT_MAX = 5000
WAIT_MAX_SECONDS = 60
_CLICK_X_Y = re.compile(r'^\s?\d+\s?,\s?\d+\s?$')


def operations():
    """{operation: (takes a selector, takes a value)}, without the form's 'Choose one'."""
    return {op: tuple(f == '1' for f in flags.split()) for op, flags in browser_step_ui_config.items()
            if op != 'Choose one'}


def _template_error(value):
    from changedetectionio.jinja2_custom.validate import _render_exception
    e = _render_exception(value)
    return str(e)[:200] if e else None


def validate_steps(steps, max_steps=100):
    """The steps checked the way they will run, as the watch stores them. Raises ValueError naming the step.

    Every step needs a known operation, a selector exactly when it takes one and a value exactly when it takes one,
    and a value that step can use: seconds, 'X,Y', a URL it may open, a template that renders. An empty list is
    valid (no steps).
    """
    from changedetectionio.jinja2_custom import JINJA2_MARKER_PATTERN
    from changedetectionio.validate_url import is_safe_valid_url
    if not isinstance(steps, list):
        raise ValueError("must be a list of steps like {\"operation\": \"Click element\", \"selector\": \"#accept\"}")
    if len(steps) > max_steps:
        raise ValueError(f"at most {max_steps} steps, this had {len(steps)}")
    known = operations()
    result = []
    for n, step in enumerate(steps, 1):
        where = f"step {n}"
        if not isinstance(step, dict):
            raise ValueError(f"{where}: must be an object with 'operation', and 'selector' / 'optional_value' when it takes them")
        unknown = set(step) - {'operation', 'selector', 'optional_value'}
        if unknown:
            raise ValueError(f"{where}: unknown key(s) {', '.join(sorted(unknown))} (allowed: operation, selector, optional_value)")
        operation = step.get('operation')
        if operation not in known:
            raise ValueError(f"{where}: operation must be one of: {', '.join(known)}")
        where = f"{where} ({operation})"
        parts = {}
        for key, takes in zip(('selector', 'optional_value'), known[operation]):
            item = step.get(key)
            if isinstance(item, bool) or (item is not None and not isinstance(item, (str, int, float))):
                raise ValueError(f"{where}: '{key}' must be text")
            item = '' if item is None else str(item)
            if len(item) > TEXT_MAX:
                raise ValueError(f"{where}: '{key}' is longer than {TEXT_MAX} characters")
            if takes and not item.strip():
                raise ValueError(f"{where}: needs a '{key}'")
            if not takes and item.strip():
                raise ValueError(f"{where}: takes no '{key}'")
            error = _template_error(item) if takes else None
            if error:
                raise ValueError(f"{where}: '{key}' is a template that doesn't render: {error}")
            parts[key] = item
        value = parts['optional_value']
        templated = bool(JINJA2_MARKER_PATTERN.search(value))
        if operation == 'Wait for seconds' and not templated:
            try:
                seconds = float(value)
            except ValueError:
                raise ValueError(f"{where}: 'optional_value' must be a number of seconds")
            if not 0 < seconds <= WAIT_MAX_SECONDS:
                raise ValueError(f"{where}: 'optional_value' must be more than 0 and at most {WAIT_MAX_SECONDS} seconds")
        elif operation == 'Click X,Y' and not _CLICK_X_Y.match(value):
            raise ValueError(f"{where}: 'optional_value' must be 'X,Y' in pixels, e.g. '100,90'")
        elif operation == 'Goto URL' and not templated and not is_safe_valid_url(value.strip()):
            # The step checks it again when it runs (rendered templates too), this is so a bad one is told now
            raise ValueError(f"{where}: 'optional_value' must be an http(s) URL it may open")
        result.append({'operation': operation, 'selector': parts['selector'], 'optional_value': value})
    return result


def json_schema(max_steps=100):
    """A JSON Schema for a list of steps, with every operation and what it takes in the description."""
    known = operations()
    takes = '; '.join(f"{op}: " + (' and '.join(n for n, t in zip(('selector', 'optional_value'), flags) if t) or 'nothing')
                      for op, flags in known.items())
    return {'type': 'array', 'maxItems': max_steps,
            'description': "Steps a real browser does before reading the page (cookie banners, logins, 'load more'), "
                           "in order; [] removes them. Each step has an operation, plus a CSS/XPath 'selector' and/or "
                           "an 'optional_value' exactly when it takes them: " + takes + ". Needs a fetcher that "
                           "supports them (Playwright or Puppeteer). Values can use Jinja2, e.g. {{ '%Y' | date }}.",
            'items': {'type': 'object', 'additionalProperties': False, 'required': ['operation'],
                      'properties': {'operation': {'type': 'string', 'enum': list(known)},
                                     'selector': {'type': 'string', 'maxLength': TEXT_MAX},
                                     'optional_value': {'type': ['string', 'number'], 'maxLength': TEXT_MAX}}}}
