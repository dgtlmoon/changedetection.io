"""File downloads in a CDP browser (puppeteer, playwright), shared by both fetchers.

When a page turns out to be a file Chrome downloads (an .msi, a zip, an attachment), the
navigation aborts and the file lands on the browser's machine. sockpuppetbrowser keeps it for
the connection and answers its own CDP methods for it (SockPuppet.supportsDownloads,
getDownload, readDownload, deleteDownload) - all over the connection that's already open, so it
works behind a load balancer and big files are hashed on the browser's side, never transferred.

Any other browser (plain Chrome, browserless, older sockpuppetbrowser) answers
"'SockPuppet.supportsDownloads' wasn't found", downloads are then denied and a download gives a
clear error instead.
"""

import asyncio
import base64
import os

from loguru import logger

from changedetectionio.content_types import BinaryContent, rule_needs_bytes

READ_CHUNK = 4 * 1024 * 1024

_warned_unsupported = False


class DownloadsNotSupported(Exception):
    pass


class CDPDownloads:
    """Download handling for one page. send/on/off are the CDP session's own, so this works the
    same for pyppeteer's CDPSession and playwright's"""

    def __init__(self, send, on, off, browser_context_id=None):
        self._send = send
        # Playwright works in its own browser context, which has its own download behaviour
        self.browser_context_id = browser_context_id
        self._on = on
        self._off = off
        self.supported = False
        self.max_size = 0
        self.started = None
        self._finished = None
        self._finished_event = asyncio.Event()

    async def setup(self):
        global _warned_unsupported
        try:
            r = await self._send('SockPuppet.supportsDownloads', {})
            self.supported = bool(r.get('supported'))
            self.max_size = int(r.get('maxSize') or 0)
        except Exception as e:
            self.supported = False
            if not _warned_unsupported:
                _warned_unsupported = True
                logger.warning(f"Browser endpoint does not support SockPuppet downloads (not sockpuppetbrowser, or an "
                               f"older version) - binary files can only be checked with the 'Basic fast Plaintext/HTTP "
                               f"Client' fetcher ({e})")

        # Without support, never let Chrome write a download to its own disk where nobody cleans it up
        params = {'behavior': 'allowAndName' if self.supported else 'deny', 'eventsEnabled': True}
        if self.browser_context_id:
            params['browserContextId'] = self.browser_context_id
        await self._send('Browser.setDownloadBehavior', params)
        self._on('Browser.downloadWillBegin', self._on_will_begin)
        self._on('Browser.downloadProgress', self._on_progress)

    def close(self):
        self._off('Browser.downloadWillBegin', self._on_will_begin)
        self._off('Browser.downloadProgress', self._on_progress)

    def _on_will_begin(self, event):
        if self.started is None:
            self.started = event
            logger.debug(f"Download started {event.get('url')} ({event.get('suggestedFilename')})")

    def _on_progress(self, event):
        if not self.started or event.get('guid') != self.started.get('guid'):
            return
        state = event.get('state')
        if state in ('completed', 'canceled'):
            self._finished = event
            self._finished_event.set()
        elif self.max_size and event.get('receivedBytes', 0) > self.max_size:
            # No point letting it finish, sockpuppetbrowser won't hand it back
            asyncio.ensure_future(self._cancel(event['guid']))

    async def _cancel(self, guid):
        try:
            await self._send('Browser.cancelDownload', {'guid': guid})
        except Exception as e:
            logger.debug(f"Browser.cancelDownload failed: {e}")

    async def result(self, rule, timeout):
        """Wait for the download to finish and describe it (BinaryContent), reading the bytes only
        when the rule needs them."""
        if not self.supported:
            raise DownloadsNotSupported("The browser downloaded a file, but this browser endpoint can't hand downloads "
                                        "back (needs a recent sockpuppetbrowser), try the 'Basic fast Plaintext/HTTP "
                                        "Client' fetcher.")

        try:
            await asyncio.wait_for(self._finished_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            raise DownloadsNotSupported(f"Download did not finish within {timeout} seconds")

        guid = self.started['guid']
        if self._finished.get('state') != 'completed':
            limit = f" (limit {self.max_size:,} bytes)" if self.max_size else ''
            raise DownloadsNotSupported(f"Download was cancelled{limit}")

        try:
            info = await self._send('SockPuppet.getDownload', {'guid': guid})
            data = None
            if rule_needs_bytes(rule):
                chunks = []
                offset = 0
                while True:
                    r = await self._send('SockPuppet.readDownload', {'guid': guid, 'offset': offset, 'size': READ_CHUNK})
                    chunk = base64.b64decode(r['data'])
                    chunks.append(chunk)
                    offset += len(chunk)
                    if r.get('eof') or not chunk:
                        break
                data = b''.join(chunks)
        finally:
            try:
                await self._send('SockPuppet.deleteDownload', {'guid': guid})
            except Exception as e:
                logger.debug(f"SockPuppet.deleteDownload failed: {e}")

        return BinaryContent(content_type=rule['content_type'], size=info['size'], sha256=info['sha256'],
                             md5=info['md5'], data=data)


def download_timeout():
    return int(os.getenv('BROWSER_DOWNLOAD_TIMEOUT_SECONDS', 120))
