"""HAR recording of a browser fetch (HAR_UUID_RECORD), built from replayed CDP Network events."""

import asyncio
import json
import zipfile

from pyee.asyncio import AsyncIOEventEmitter

from changedetectionio.content_fetchers.har_recorder import HarRecorder, har_from_requests_responses, \
    har_recording_wanted, save_har


class FakeCDPSession(AsyncIOEventEmitter):
    def __init__(self, bodies):
        super().__init__()
        self.bodies = bodies

    async def send(self, method, params=None):
        assert method == 'Network.getResponseBody'
        if params['requestId'] not in self.bodies:
            raise Exception('No resource with given identifier found')
        return {'body': self.bodies[params['requestId']], 'base64Encoded': False}


def test_uuid_list_is_comma_separated_and_case_insensitive():
    uuid = 'aBcDef12-0000-4000-8000-000000000001'
    assert har_recording_wanted(uuid, env_value=f'something-else, {uuid.upper()} ')
    assert har_recording_wanted(uuid, env_value=f'"{uuid.lower()}"')
    assert not har_recording_wanted(uuid, env_value='something-else')
    assert not har_recording_wanted(uuid, env_value='')
    assert not har_recording_wanted(None, env_value=uuid)


def test_events_become_har_entries(tmp_path):
    async def scenario():
        client = FakeCDPSession(bodies={'1': '<html>landed</html>'})
        recorder = HarRecorder(client, title='the watch url')
        recorder.start()

        # A redirect re-uses the requestId, so one id has to turn into two entries
        client.emit('Network.requestWillBeSent', {
            'requestId': '1', 'timestamp': 10.0, 'wallTime': 1700000000.0, 'type': 'Document',
            'request': {'url': 'http://site/start?a=1&b=', 'method': 'GET', 'headers': {'Accept': '*/*'}}})
        # Real headers arrive separately, and are the only place the cookies show up
        client.emit('Network.requestWillBeSentExtraInfo', {
            'requestId': '1', 'headers': {'Accept': '*/*', 'Cookie': 'session=abc; theme=dark'}})
        client.emit('Network.requestWillBeSent', {
            'requestId': '1', 'timestamp': 10.2, 'wallTime': 1700000000.2, 'type': 'Document',
            'request': {'url': 'http://site/landed', 'method': 'GET', 'headers': {}},
            'redirectResponse': {'status': 302, 'statusText': 'Found', 'protocol': 'http/1.1',
                                 'headers': {'Location': '/landed', 'Set-Cookie': 'a=1; Path=/\nb=2'}}})
        client.emit('Network.responseReceived', {
            'requestId': '1', 'type': 'Document',
            'response': {'status': 200, 'statusText': 'OK', 'protocol': 'h2', 'mimeType': 'text/html',
                         'headers': {'Content-Type': 'text/html'}, 'remoteIPAddress': '[::1]'}})
        client.emit('Network.dataReceived', {'requestId': '1', 'dataLength': 19})
        client.emit('Network.loadingFinished', {'requestId': '1', 'timestamp': 10.5, 'encodedDataLength': 19})

        # A blocked subresource, the browser has no body for it
        client.emit('Network.requestWillBeSent', {
            'requestId': '2', 'timestamp': 10.6, 'wallTime': 1700000000.6, 'type': 'Script',
            'request': {'url': 'http://site/challenge.js', 'method': 'GET', 'headers': {}}})
        client.emit('Network.loadingFailed', {'requestId': '2', 'timestamp': 10.7, 'errorText': 'net::ERR_ABORTED'})

        # Inline data is not network traffic, and a broken event must never escape the listener
        client.emit('Network.requestWillBeSent', {
            'requestId': '3', 'request': {'url': 'data:image/png;base64,AAAA', 'method': 'GET'}})
        client.emit('Network.requestWillBeSent', {})

        await recorder.stop()
        assert not client.listeners('Network.requestWillBeSent'), "stop() must detach from the session"
        return recorder

    recorder = asyncio.run(scenario())
    destination, n = recorder.save(str(tmp_path))
    assert n == 3

    with zipfile.ZipFile(destination) as z:
        assert z.namelist() == ['har-record.har']
        har = json.loads(z.read('har-record.har'))

    log = har['log']
    assert log['version'] == '1.2'
    assert log['pages'][0]['title'] == 'the watch url'
    first, landed, blocked = log['entries']

    assert first['request']['url'] == 'http://site/start?a=1&b='
    assert first['request']['queryString'] == [{'name': 'a', 'value': '1'}, {'name': 'b', 'value': ''}]
    assert first['request']['cookies'] == [{'name': 'session', 'value': 'abc'}, {'name': 'theme', 'value': 'dark'}]
    assert first['response']['status'] == 302
    assert first['response']['redirectURL'] == '/landed'
    assert first['response']['cookies'] == [{'name': 'a', 'value': '1'}, {'name': 'b', 'value': '2'}]
    assert first['time'] == 200.0
    assert 'text' not in first['response']['content']

    assert landed['request']['url'] == 'http://site/landed'
    assert landed['response']['status'] == 200
    assert landed['response']['httpVersion'] == 'HTTP/2.0'
    assert landed['response']['content'] == {'size': 19, 'mimeType': 'text/html', 'text': '<html>landed</html>'}
    assert landed['serverIPAddress'] == '::1'

    assert blocked['_error'] == 'net::ERR_ABORTED'
    assert blocked['response']['status'] == 0

    # The next check replaces the file instead of piling them up
    recorder.save(str(tmp_path))
    assert [p.name for p in tmp_path.iterdir()] == ['har-record.zip']


def _har_with(mime_type):
    return {'log': {'entries': [{'response': {'content': {'size': 4, 'mimeType': mime_type,
                                                         'text': 'AAAA', 'encoding': 'base64'}}}]}}


def test_binary_bodies_are_left_out_unless_asked_for(tmp_path, monkeypatch):
    monkeypatch.setenv('HAR_FORMAT', 'har')
    monkeypatch.delenv('HAR_INCLUDE_BINARY', raising=False)

    def saved_content(mime_type):
        with open(save_har(str(tmp_path), _har_with(mime_type))) as f:
            return json.load(f)['log']['entries'][0]['response']['content']

    # The request is still listed with its size, only the payload is gone
    image = saved_content('image/png')
    assert 'text' not in image and 'encoding' not in image
    assert image['size'] == 4 and 'HAR_INCLUDE_BINARY' in image['comment']

    for readable in ('text/html; charset=utf-8', 'application/json', 'application/javascript', 'image/svg+xml'):
        assert saved_content(readable)['text'] == 'AAAA', readable

    monkeypatch.setenv('HAR_INCLUDE_BINARY', 'true')
    assert saved_content('image/png')['text'] == 'AAAA'


def test_har_format_selects_plain_har_or_zip(tmp_path, monkeypatch):
    monkeypatch.delenv('HAR_FORMAT', raising=False)
    assert save_har(str(tmp_path), _har_with('text/html')).endswith('har-record.zip')

    # Switching format must not leave the old recording lying around next to the new one
    monkeypatch.setenv('HAR_FORMAT', 'HAR')
    destination = save_har(str(tmp_path), _har_with('text/html'))
    assert [p.name for p in tmp_path.iterdir()] == ['har-record.har']
    with open(destination) as f:
        assert json.load(f)['log']['entries']

    monkeypatch.setenv('HAR_FORMAT', 'nonsense')
    save_har(str(tmp_path), _har_with('text/html'))
    assert [p.name for p in tmp_path.iterdir()] == ['har-record.zip']


def test_requests_responses_become_har_entries(monkeypatch):
    """The `requests` fetcher hands over the response of each hop"""
    from datetime import timedelta
    from types import SimpleNamespace

    def response(url, status, headers, body=b'', encoding='utf-8', request_headers=None):
        return SimpleNamespace(
            request=SimpleNamespace(method='GET', url=url, headers=request_headers or {}, body=None),
            raw=SimpleNamespace(headers=SimpleNamespace(items=lambda: headers), version=11),
            status_code=status, reason='whatever', content=body, encoding=encoding,
            elapsed=timedelta(milliseconds=120))

    monkeypatch.delenv('HAR_INCLUDE_BINARY', raising=False)
    recorded = [
        (1700000000.0, response('http://site/start?a=1', 302,
                                [('Location', '/img.png'), ('Set-Cookie', 'a=1; Path=/'), ('Set-Cookie', 'b=2')],
                                request_headers={'Cookie': 'session=abc'})),
        (1700000000.2, response('http://site/img.png', 200, [('Content-Type', 'image/png')], body=b'\x89PNG')),
        (1700000000.4, response('http://site/page', 200, [('Content-Type', 'text/html')], body='héllo'.encode())),
    ]
    redirect, image, page = har_from_requests_responses(recorded, title='t')['log']['entries']

    assert redirect['response']['status'] == 302
    assert redirect['response']['redirectURL'] == '/img.png'
    assert redirect['response']['cookies'] == [{'name': 'a', 'value': '1'}, {'name': 'b', 'value': '2'}]
    assert redirect['request']['cookies'] == [{'name': 'session', 'value': 'abc'}]
    assert redirect['request']['queryString'] == [{'name': 'a', 'value': '1'}]
    assert redirect['time'] == 120.0 and redirect['response']['httpVersion'] == 'HTTP/1.1'

    assert image['response']['content'] == {'size': 4, 'mimeType': 'image/png'}
    assert page['response']['content']['text'] == 'héllo'

    monkeypatch.setenv('HAR_INCLUDE_BINARY', '1')
    image = har_from_requests_responses(recorded)['log']['entries'][1]
    assert image['response']['content']['encoding'] == 'base64'
