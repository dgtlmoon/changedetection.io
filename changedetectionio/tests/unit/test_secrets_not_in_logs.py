"""Passwords and access tokens stay out of the log output.

Notification URLs carry their own credentials and the browser connection URL carries the access
token of the browser service, neither belongs in a log line.
"""

import asyncio

import pytest
from loguru import logger

SECRET = 's3cretPassw0rd-9f1c'


@pytest.fixture
def log_lines():
    lines = []
    sink = logger.add(lambda message: lines.append(str(message)), level='TRACE')
    yield lines
    logger.remove(sink)


@pytest.mark.parametrize('url', [
    f'mailto://someuser:{SECRET}@example.com?to=someone@example.com',
    f'post://someuser:{SECRET}@example.com/notify',
    f'json://someuser:{SECRET}@example.com/notify',
])
def test_notification_url_is_masked(url):
    from changedetectionio.notification.masking import mask_notification_url

    masked = mask_notification_url(url)
    assert SECRET not in masked
    # Still says where it goes
    assert masked.startswith(url.split('://')[0] + '://') and 'example.com' in masked


def test_notification_url_that_cannot_be_read_is_masked_whole():
    from changedetectionio.notification.masking import mask_notification_url

    assert mask_notification_url(f'nosuchservice://{SECRET}/path') == 'nosuchservice://****'
    assert mask_notification_url(SECRET) == '****'


def test_sent_notifications_are_masked_as_a_copy():
    from changedetectionio.notification.masking import mask_sent_notifications

    url = f'post://someuser:{SECRET}@example.com/notify'
    sent = [{'title': 'Changed', 'body': 'A change', 'url': url,
             'original_context': {'watch_url': 'https://example.com', 'notification_urls': [url]}}]

    masked = mask_sent_notifications(sent)

    assert SECRET not in str(masked)
    assert masked[0]['title'] == 'Changed' and masked[0]['original_context']['watch_url'] == 'https://example.com'
    # What was sent is still what it was
    assert sent[0]['url'] == url and sent[0]['original_context']['notification_urls'] == [url]
    assert mask_sent_notifications(None) == []


def test_browser_address_for_logs_drops_the_token_and_proxy():
    from changedetectionio.content_fetchers.base import browser_address_for_logs

    url = f'ws://browser.example:3000/?token={SECRET}&stealth=1&--proxy-server=http://proxy.example:8080'
    assert browser_address_for_logs(url) == 'ws://browser.example:3000'
    assert browser_address_for_logs('wss://browser.example') == 'wss://browser.example'


def test_puppeteer_connect_does_not_log_the_browser_token(log_lines):
    from changedetectionio.content_fetchers.exceptions import BrowserConnectError
    from changedetectionio.content_fetchers.puppeteer import fetcher

    # Nothing listens there, the connection is refused straight away
    browser = fetcher(custom_browser_connection_url=f'ws://127.0.0.1:1/?token={SECRET}')
    with pytest.raises(BrowserConnectError) as error:
        asyncio.run(browser.run(url='http://127.0.0.1:1/', watch_uuid='secret-test', fetch_favicon=False,
                                current_include_filters=None, request_headers={}, request_method='GET', timeout=5))

    assert any('Connecting to browser at ws://127.0.0.1:1' in line for line in log_lines)
    assert not [line for line in log_lines if SECRET in line], "The browser token was logged"
    assert SECRET not in str(error.value.msg)
