"""Record the network traffic of one browser fetch as a HAR 1.2 file.

Diagnostic aid for "why does this site block/behave differently for the browser" (#4539).

The playwright fetcher uses playwright's own HAR recording and only needs save_har_file() from here.
pyppeteer has none, so HarRecorder builds the HAR from raw CDP Network events - it only needs a CDP
session object offering .on() / .remove_listener() / .send().
`requests` has none either, har_from_requests_responses() builds it from the responses of each hop.

Only loaded when recording is switched on for a watch, see HAR_UUID_RECORD in the browser fetchers.

    HAR_UUID_RECORD     comma separated watch UUIDs to record (case insensitive)
    HAR_FORMAT          'zip' (default, har-record.zip holding har-record.har) or 'har' (plain har-record.har)
    HAR_INCLUDE_BINARY  also keep the bodies of images, fonts, media etc, off by default - every request
                        is always listed with its headers and sizes, this is only about the payload
"""
import asyncio
import json
import os
import zipfile
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlsplit

from loguru import logger

from changedetectionio.strtobool import strtobool

HAR_ZIP_FILENAME = 'har-record.zip'
HAR_FILENAME = 'har-record.har'
# Bodies worth reading when working out why a page behaves the way it does
TEXT_MIME_MARKERS = ('json', 'xml', 'javascript', 'ecmascript', 'html', 'urlencoded')

# Response bodies larger than this are listed with their size but not embedded
MAX_EMBEDDED_BODY_BYTES = 2 * 1024 * 1024
# How long to let in-flight body reads finish once the fetch is over
BODY_DRAIN_TIMEOUT_SECONDS = 5


def har_recording_wanted(watch_uuid, env_value=None):
    """True when watch_uuid is in the comma separated HAR_UUID_RECORD list (case insensitive)."""
    if env_value is None:
        env_value = os.getenv('HAR_UUID_RECORD', '')
    if not watch_uuid or not env_value:
        return False
    wanted = {u.strip().strip('"\'').lower() for u in env_value.split(',')}
    return str(watch_uuid).lower() in wanted


def include_binary_bodies():
    return bool(strtobool(os.getenv('HAR_INCLUDE_BINARY', 'False')))


def is_text_mime_type(mime_type):
    mime_type = (mime_type or '').lower()
    return mime_type.startswith('text/') or any(m in mime_type for m in TEXT_MIME_MARKERS)


def strip_binary_bodies(har):
    """Drop the payload of images, fonts, media etc, their entries stay with headers and sizes."""
    for entry in har.get('log', {}).get('entries', []):
        content = entry.get('response', {}).get('content') or {}
        if 'text' in content and not is_text_mime_type(content.get('mimeType')):
            del content['text']
            content.pop('encoding', None)
            content['comment'] = 'Binary body not recorded, set HAR_INCLUDE_BINARY=true to keep it'
    return har


def save_har(directory, har):
    """Write the HAR into directory as HAR_FORMAT asks, replacing the one from the previous check. Blocking."""
    if not include_binary_bodies():
        strip_binary_bodies(har)

    har_format = os.getenv('HAR_FORMAT', 'zip').strip().lower() or 'zip'
    if har_format not in ('zip', 'har'):
        logger.warning(f"HAR_FORMAT '{har_format}' is not 'zip' or 'har', using 'zip'")
        har_format = 'zip'

    filename, other = (HAR_ZIP_FILENAME, HAR_FILENAME) if har_format == 'zip' else (HAR_FILENAME, HAR_ZIP_FILENAME)
    destination = os.path.join(directory, filename)
    tmp = destination + '.tmp'
    if har_format == 'zip':
        with zipfile.ZipFile(tmp, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr(HAR_FILENAME, json.dumps(har))
    else:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(har, f)
    os.replace(tmp, destination)

    # Only ever one recording per watch, don't leave a stale one behind when HAR_FORMAT was changed
    stale = os.path.join(directory, other)
    if os.path.exists(stale):
        os.unlink(stale)
    return destination


def save_har_file(directory, har_file):
    """Same as save_har() for a HAR that some other recorder already wrote to har_file. Blocking."""
    with open(har_file, 'r', encoding='utf-8') as f:
        return save_har(directory, json.load(f))


def _name_value_list(headers):
    # CDP gives a dict and folds repeated headers (Set-Cookie) into one value joined by newlines
    out = []
    for name, value in (headers or {}).items():
        for v in str(value).split('\n'):
            out.append({'name': name, 'value': v})
    return out


def _header(headers, wanted):
    for name, value in (headers or {}).items():
        if name.lower() == wanted:
            return str(value)
    return ''


def _request_cookies(headers):
    out = []
    for part in _header(headers, 'cookie').split(';'):
        name, sep, value = part.strip().partition('=')
        if sep:
            out.append({'name': name, 'value': value})
    return out


def _response_cookies(headers):
    out = []
    for line in _header(headers, 'set-cookie').split('\n'):
        name, sep, value = line.split(';', 1)[0].strip().partition('=')
        if sep:
            out.append({'name': name, 'value': value})
    return out


def _iso(wall_time):
    return datetime.fromtimestamp(wall_time or 0, tz=timezone.utc).isoformat(timespec='milliseconds')


def _http_version(protocol):
    return {'h2': 'HTTP/2.0', 'h3': 'HTTP/3.0'}.get(protocol or '', (protocol or '').upper())


def har_from_requests_responses(recorded, title=''):
    """Build a HAR from `requests` responses, one entry per hop.

    recorded is a list of (wall clock time the request started, requests.Response), which the
    requests fetcher collects with a session 'response' hook so every redirect hop is in there.
    """
    import base64
    entries = []
    keep_binary = include_binary_bodies()
    for started, r in recorded:
        request = r.request
        request_headers = dict(request.headers or {})

        # r.headers folds repeated headers (Set-Cookie) together with commas, the raw ones are still separate
        response_headers = {}
        try:
            pairs = list(r.raw.headers.items())
        except Exception:
            pairs = list(r.headers.items())
        for name, value in pairs:
            response_headers[name] = f"{response_headers[name]}\n{value}" if name in response_headers else value

        mime_type = _header(response_headers, 'content-type')
        body = r.content or b''
        content = {'size': len(body), 'mimeType': mime_type}
        if body and len(body) <= MAX_EMBEDDED_BODY_BYTES:
            if is_text_mime_type(mime_type):
                try:
                    content['text'] = body.decode(r.encoding or 'utf-8')
                except (UnicodeDecodeError, LookupError):
                    content['text'] = base64.b64encode(body).decode('ascii')
                    content['encoding'] = 'base64'
            elif keep_binary:
                content['text'] = base64.b64encode(body).decode('ascii')
                content['encoding'] = 'base64'

        request_body = request.body or ''
        if isinstance(request_body, bytes):
            request_body = request_body.decode('utf-8', errors='replace')
        http_version = {10: 'HTTP/1.0', 11: 'HTTP/1.1', 20: 'HTTP/2.0'}.get(getattr(r.raw, 'version', None), '')
        elapsed = round(r.elapsed.total_seconds() * 1000, 3)

        har_request = {
            'method': request.method or '',
            'url': request.url or '',
            'httpVersion': http_version,
            'cookies': _request_cookies(request_headers),
            'headers': _name_value_list(request_headers),
            'queryString': [{'name': n, 'value': v} for n, v in
                            parse_qsl(urlsplit(request.url or '').query, keep_blank_values=True)],
            'headersSize': -1,
            'bodySize': len(request_body),
        }
        if request_body:
            har_request['postData'] = {'mimeType': _header(request_headers, 'content-type'), 'text': request_body}

        entries.append({
            'pageref': 'page_1',
            'startedDateTime': _iso(started),
            'time': elapsed,
            'request': har_request,
            'response': {
                'status': r.status_code,
                'statusText': r.reason or '',
                'httpVersion': http_version,
                'cookies': _response_cookies(response_headers),
                'headers': _name_value_list(response_headers),
                'content': content,
                'redirectURL': _header(response_headers, 'location'),
                'headersSize': -1,
                'bodySize': len(body),
            },
            'cache': {},
            # requests only measures request-sent to headers-parsed
            'timings': {'blocked': -1, 'dns': -1, 'connect': -1, 'ssl': -1, 'send': 0, 'wait': elapsed, 'receive': 0},
        })
    return _har_log(entries, title)


def _har_log(entries, title):
    started = entries[0]['startedDateTime'] if entries else _iso(None)
    return {
        'log': {
            'version': '1.2',
            'creator': {'name': 'changedetection.io', 'version': '1'},
            'pages': [{'startedDateTime': started, 'id': 'page_1', 'title': title,
                       'pageTimings': {'onContentLoad': -1, 'onLoad': -1}}],
            'entries': entries,
        }
    }


class HarRecorder:
    def __init__(self, cdp_session, title=''):
        self.client = cdp_session
        self.title = title
        # One CDP requestId covers a whole redirect chain, so each id holds a list of hops
        self.hops = {}
        # The *ExtraInfo events carry the headers as really sent/received (cookies included), they
        # arrive in hop order but can land before or after the main event, so pair them up at build time
        self.extra_request_headers = {}
        self.extra_response_headers = {}
        self.order = []
        self._body_tasks = set()
        self._handlers = {
            'Network.requestWillBeSent': self._safe(self._on_request),
            'Network.requestWillBeSentExtraInfo': self._safe(self._on_request_extra),
            'Network.responseReceived': self._safe(self._on_response),
            'Network.responseReceivedExtraInfo': self._safe(self._on_response_extra),
            'Network.dataReceived': self._safe(self._on_data),
            'Network.loadingFinished': self._safe(self._on_finished),
            'Network.loadingFailed': self._safe(self._on_failed),
        }

    @staticmethod
    def _safe(fn):
        # An exception escaping a CDP listener can take the whole browser connection down with it,
        # and a diagnostic recorder must never be the reason a check fails
        def wrapped(event):
            try:
                fn(event)
            except Exception as e:
                logger.debug(f"HAR recorder ignored a malformed event: {e}")
        return wrapped

    def start(self):
        for name, handler in self._handlers.items():
            self.client.on(name, handler)

    async def stop(self):
        for name, handler in self._handlers.items():
            try:
                self.client.remove_listener(name, handler)
            except Exception:
                pass
        if self._body_tasks:
            # Deliberately not cancelled on timeout - abandoning a CDP request half way can leave
            # the connection unusable, and the caller closes the page straight after this anyway
            await asyncio.wait(self._body_tasks, timeout=BODY_DRAIN_TIMEOUT_SECONDS)

    def _current(self, event):
        hops = self.hops.get(event.get('requestId'))
        return hops[-1] if hops else None

    def _on_request(self, event):
        request = event.get('request', {})
        if request.get('url', '').startswith('data:'):
            return
        request_id = event['requestId']
        hops = self.hops.setdefault(request_id, [])
        if hops and event.get('redirectResponse'):
            # Same id re-used for the next hop, the previous one ended with this redirect
            previous = hops[-1]
            previous['response'] = event['redirectResponse']
            previous['end'] = event.get('timestamp')
        hop = {
            'request': request,
            'start': event.get('timestamp'),
            'wall': event.get('wallTime'),
            'type': event.get('type'),
            'size': 0,
        }
        hops.append(hop)
        self.order.append(hop)

    def _on_request_extra(self, event):
        self.extra_request_headers.setdefault(event['requestId'], []).append(event.get('headers'))

    def _on_response_extra(self, event):
        self.extra_response_headers.setdefault(event['requestId'], []).append(event.get('headers'))

    def _on_response(self, event):
        hop = self._current(event)
        if hop:
            hop['response'] = event.get('response')
            hop['type'] = event.get('type') or hop.get('type')

    def _on_data(self, event):
        hop = self._current(event)
        if hop:
            hop['size'] += event.get('dataLength', 0)

    def _on_finished(self, event):
        hop = self._current(event)
        if not hop:
            return
        hop['end'] = event.get('timestamp')
        hop['encoded_size'] = event.get('encodedDataLength')
        wanted = include_binary_bodies() or is_text_mime_type((hop.get('response') or {}).get('mimeType'))
        if wanted and hop['size'] <= MAX_EMBEDDED_BODY_BYTES:
            task = asyncio.ensure_future(self._read_body(event['requestId'], hop))
            self._body_tasks.add(task)
            task.add_done_callback(self._body_tasks.discard)

    def _on_failed(self, event):
        hop = self._current(event)
        if hop:
            hop['end'] = event.get('timestamp')
            hop['error'] = event.get('errorText') or 'failed'

    async def _read_body(self, request_id, hop):
        try:
            r = await self.client.send('Network.getResponseBody', {'requestId': request_id})
            hop['body'] = r.get('body', '')
            hop['body_base64'] = bool(r.get('base64Encoded'))
        except Exception:
            # Normal for bodies the browser already dropped (an earlier document, a 204, a closed page)
            pass

    def _entry(self, hop, request_headers, response_headers):
        request = hop['request']
        response = hop.get('response') or {}
        request_headers = request_headers or request.get('headers')
        response_headers = response_headers or response.get('headers')
        http_version = _http_version(response.get('protocol'))

        har_request = {
            'method': request.get('method', ''),
            'url': request.get('url', ''),
            'httpVersion': http_version,
            'cookies': _request_cookies(request_headers),
            'headers': _name_value_list(request_headers),
            'queryString': [{'name': n, 'value': v} for n, v in
                            parse_qsl(urlsplit(request.get('url', '')).query, keep_blank_values=True)],
            'headersSize': -1,
            'bodySize': len(request.get('postData') or ''),
        }
        if request.get('postData'):
            har_request['postData'] = {'mimeType': _header(request_headers, 'content-type'),
                                       'text': request['postData']}

        content = {'size': hop.get('size', 0), 'mimeType': response.get('mimeType', '')}
        if 'body' in hop:
            content['text'] = hop['body']
            if hop.get('body_base64'):
                content['encoding'] = 'base64'

        # CDP timing offsets are milliseconds relative to requestTime, -1 when the phase did not happen
        timing = response.get('timing') or {}

        def phase(start, end):
            s, e = timing.get(start, -1), timing.get(end, -1)
            return round(e - s, 3) if s >= 0 and e >= s else -1

        total = round(max((hop.get('end') or hop.get('start') or 0) - (hop.get('start') or 0), 0) * 1000, 3)
        wait = phase('sendEnd', 'receiveHeadersEnd')
        receive = -1
        if timing.get('requestTime') and hop.get('end') and timing.get('receiveHeadersEnd', -1) >= 0:
            receive = round(max((hop['end'] - timing['requestTime']) * 1000 - timing['receiveHeadersEnd'], 0), 3)

        entry = {
            'pageref': 'page_1',
            'startedDateTime': _iso(hop.get('wall')),
            'time': total,
            'request': har_request,
            'response': {
                'status': response.get('status', 0),
                'statusText': response.get('statusText', ''),
                'httpVersion': http_version,
                'cookies': _response_cookies(response_headers),
                'headers': _name_value_list(response_headers),
                'content': content,
                'redirectURL': _header(response_headers, 'location'),
                'headersSize': -1,
                'bodySize': hop.get('encoded_size', -1),
            },
            'cache': {},
            'timings': {
                'blocked': -1,
                'dns': phase('dnsStart', 'dnsEnd'),
                'connect': phase('connectStart', 'connectEnd'),
                'ssl': phase('sslStart', 'sslEnd'),
                'send': max(phase('sendStart', 'sendEnd'), 0),
                'wait': max(wait, 0),
                'receive': max(receive, 0),
            },
            '_resourceType': (hop.get('type') or '').lower(),
        }
        if response.get('remoteIPAddress'):
            entry['serverIPAddress'] = response['remoteIPAddress'].strip('[]')
        if response.get('fromDiskCache'):
            entry['_fromCache'] = 'disk'
        if hop.get('error'):
            entry['_error'] = hop['error']
        return entry

    def to_har(self):
        for request_id, hops in self.hops.items():
            req_extra = self.extra_request_headers.get(request_id, [])
            res_extra = self.extra_response_headers.get(request_id, [])
            for i, hop in enumerate(hops):
                hop['_entry'] = self._entry(hop,
                                            req_extra[i] if i < len(req_extra) else None,
                                            res_extra[i] if i < len(res_extra) else None)
        # Keep the order the browser issued them in
        entries = [hop['_entry'] for hop in self.order if '_entry' in hop]
        return _har_log(entries, self.title)

    def save(self, directory):
        """Save into directory, see save_har(). Blocking."""
        har = self.to_har()
        return save_har(directory, har), len(har['log']['entries'])
