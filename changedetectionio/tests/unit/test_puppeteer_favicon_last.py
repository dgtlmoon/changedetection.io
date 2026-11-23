"""The favicon is fetched last and never holds a fetch up.

The in-page favicon fetcher bounds itself with the page's own timers. On a page that keeps the
browser's main thread busy those hardly fire: it took 100s+ and the fetch ran out of time with the
content already in hand. The wait for it is bounded from outside the page, and the browser's own
copy of the icon is what is used when it does not come back.
"""

import asyncio
import time
from types import SimpleNamespace

from changedetectionio.content_fetchers import puppeteer

ICON = 'http://localhost/icon.png'
BROWSER_COPY = {'url': ICON, 'mime_type': 'image/png', 'base64': 'YnJvd3Nlcg=='}
IN_PAGE = {'url': ICON, 'mime_type': 'image/png', 'base64': 'aW4tcGFnZQ=='}


def _fake_page(calls, in_page):
    async def evaluate(script, *args):
        if script == puppeteer.FAVICON_CANDIDATE_URLS_JS:
            return [ICON]
        if script == puppeteer.FAVICON_FETCHER_JS:
            calls.append('in-page fetcher')
            if in_page == 'never answers':
                await asyncio.sleep(3600)
            if in_page == 'fails':
                raise RuntimeError('Execution context was destroyed')
            return in_page

    async def send(method, params=None):
        if method == 'Emulation.setScriptExecutionDisabled':
            calls.append(('scripts paused', params['value']))
        if method == 'Network.getResponseBody':
            calls.append('browser copy')
            return {'body': BROWSER_COPY['base64'], 'base64Encoded': True}
        return {}

    return SimpleNamespace(evaluate=evaluate, _client=SimpleNamespace(send=send))


def _fetch(in_page, scripts_paused=True):
    calls = []
    page = _fake_page(calls, in_page)
    favicon = asyncio.run(puppeteer.fetch_favicon_last(page, {ICON: ('request-1', 'image/png')}, 'uuid', scripts_paused))
    return favicon, calls


def test_page_that_never_answers_does_not_hold_the_fetch(monkeypatch):
    monkeypatch.setattr(puppeteer, 'FAVICON_FETCH_TIMEOUT_SECONDS', 0.2)
    started = time.time()
    favicon, calls = _fetch('never answers')

    assert time.time() - started < 5
    assert favicon == BROWSER_COPY, "The browser's own copy of the icon should have been used"


def test_browser_copy_is_read_while_the_page_is_held_then_the_page_runs_again():
    favicon, calls = _fetch(IN_PAGE)

    # The in-page fetcher needs the page's timers, so only after the scripts are handed back
    assert calls == ['browser copy', ('scripts paused', False), 'in-page fetcher']
    assert favicon == IN_PAGE, "An icon the page could fetch itself is preferred"


def test_in_page_fetcher_coming_back_empty_or_failing_uses_the_browser_copy():
    assert _fetch(None)[0] == BROWSER_COPY
    assert _fetch({'url': ICON, 'base64': ''})[0] == BROWSER_COPY
    assert _fetch('fails')[0] == BROWSER_COPY


def test_scripts_that_were_not_paused_are_left_alone():
    favicon, calls = _fetch(IN_PAGE, scripts_paused=False)

    assert ('scripts paused', False) not in calls
