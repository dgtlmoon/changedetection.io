"""HAR recording of a browser fetch (HAR_UUID_RECORD), built from replayed CDP Network events."""

import asyncio
import json
import zipfile

from pyee.asyncio import AsyncIOEventEmitter

from changedetectionio.content_fetchers.har_recorder import HarRecorder, har_recording_wanted


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
