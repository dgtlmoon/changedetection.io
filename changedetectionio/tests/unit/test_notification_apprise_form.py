#!/usr/bin/env python3
"""notification/apprise_form.py: Apprise's service descriptions as small form descriptions, and form
values back into Apprise URLs, for the notification setup widget."""
import apprise

from changedetectionio.notification.apprise_form import GENERIC_ARGS, build_url, describe_service, list_services


def _keys(fields):
    return [f['key'] for f in fields]


def test_list_services():
    # Registers changedetection.io's own get:// post:// ... handlers with Apprise
    import changedetectionio.notification.apprise_plugin.custom_handlers  # noqa: F401

    services = {s['schema']: s for s in list_services()}
    assert services['discord']['name'] == 'Discord'
    assert services['tgram']['setup_url']
    # The secure scheme is the one listed when a service has both
    assert 'jsons' in services and 'json' not in services
    # Only real Apprise services, not changedetection.io's own get:// post:// handlers
    assert not {'get', 'gets', 'post', 'posts', 'put', 'puts', 'delete', 'deletes'} & set(services)
    # Plain SMTP e-mail is "Custom e-mail", so it isn't mistaken for the ready-made e-mail box
    assert services['mailtos']['name'] == 'Custom e-mail'
    assert describe_service('mailtos')['name'] == 'Custom e-mail'

    assert [s['schema'] for s in list_services('telegr')] == ['tgram']
    # Matches the scheme too
    assert 'tgram' in [s['schema'] for s in list_services('tgram')]


def test_describe_telegram():
    form = describe_service('tgram')
    assert form['name'] == 'Telegram'
    assert form['secure_toggle'] is False
    keys = _keys(form['fields'])
    # No `schema` field, and the single-item token is folded into the list field it belongs to
    assert 'schema' not in keys and 'target_user' not in keys
    targets = next(f for f in form['fields'] if f['key'] == 'targets')
    assert targets['type'] == 'list'
    assert targets['label'] != 'Targets', "The list should be labelled after its items"
    token = form['fields'][0]
    assert token['key'] == 'bot_token' and token['required'] and token['type'] == 'password'
    # Generic transport options and aliases stay out of the form
    option_keys = _keys(form['options'])
    assert not GENERIC_ARGS & set(option_keys)
    assert 'thread' not in option_keys, "alias_of entries are skipped"
    assert 'silent' in option_keys


def test_describe_secure_toggle_and_headers():
    form = describe_service('jsons')
    assert form['secure_toggle'] is True
    assert {'key': 'headers', 'label': 'HTTP Header', 'prefix': '+'} in form['kwargs']


def test_describe_unknown():
    assert describe_service('not-a-service') is None
    assert describe_service('') is None


def test_describe_translated_labels():
    # Apprise ships its own translations for these labels
    form = describe_service('tgram', lang='de')
    assert form['fields'][0]['label'] == 'Bot-Token'
    # and the language doesn't stick
    assert describe_service('tgram')['fields'][0]['label'] == 'Bot Token'


def test_build_telegram():
    result = build_url('tgram', {'bot_token': '123456:abcDEF_ghi', 'targets': '-1001234, channelname',
                                 'silent': True, 'detect': True})
    url = result['url']
    assert url.startswith('tgram://123456')
    assert 'silent=yes' in url
    # detect=yes is the default, and the generic options are never written
    assert 'detect=' not in url
    for generic in ('overflow=', 'wait=', 'retry=', 'format='):
        assert generic not in url
    assert 'abcDEF' not in result['url_masked']

    # Reads back the way it will be at send time
    instance = apprise.Apprise.instantiate(url)
    assert [str(t[0]) for t in instance.targets] == ['-1001234', '@channelname']


def test_build_errors():
    result = build_url('discord', {'webhook_id': '1234567'})
    assert result['missing'] == ['Webhook Token']

    result = build_url('tgram', {'bot_token': 'nope'})
    assert 'Bot Token' in result['error'] and 'invalid' in result['error']

    assert 'error' in build_url('not-a-service', {})


def test_build_keeps_non_default_port_and_headers():
    url = build_url('mailtos', {'user': 'me', 'password': 'pw', 'host': 'smtp.example.com', 'port': '2525',
                                'targets': 'a@example.com\nb@example.com'})['url']
    instance = apprise.Apprise.instantiate(url)
    assert instance.port == 2525
    assert instance.targets[0][1] == 'a@example.com' and len(instance.targets) == 2

    url = build_url('jsons', {'host': 'hooks.example.com'}, secure=False, extra={'headers': {'X-Token': 'abc'}})['url']
    assert url.startswith('json://')
    assert apprise.Apprise.instantiate(url).headers == {'X-Token': 'abc'}
