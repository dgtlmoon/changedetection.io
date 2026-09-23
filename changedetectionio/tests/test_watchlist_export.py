import csv
import re
from io import StringIO

from flask import url_for


def test_export_selected_watches(client):
    datastore = client.application.config['DATASTORE']
    first = datastore.add_watch(url='https://example.com/first', extras={
        'paused': True, 'title': '商品, "A"\nSecond line',
        'last_error': 'HTTP 503, retry later',
        'restock': {'in_stock': False, 'price': 0, 'currency': 'EUR'},
    })
    # add_watch intentionally drops runtime timestamps from imported settings.
    datastore.data['watching'][first]['last_checked'] = 1750000000
    second = datastore.add_watch(url='https://example.com/second', extras={'paused': True})
    datastore.add_watch(url='https://example.com/not-selected', extras={'paused': True})
    response = client.post(url_for('ui.export_selected_watches'), data={
        'uuids': [second, ' ' + first + ' ', first, 'deleted-watch'],
    })
    assert response.status_code == 200
    assert response.is_streamed
    assert response.content_type == 'text/csv; charset=utf-8'
    assert 'attachment;' in response.headers['Content-Disposition']
    assert response.headers['Cache-Control'] == 'no-store'
    rows = list(csv.DictReader(StringIO(response.data.decode('utf-8-sig'))))
    assert [row['uuid'] for row in rows] == [second, first]
    assert rows[1]['title'] == '商品, "A"\nSecond line'
    assert rows[1]['last_error'] == 'HTTP 503, retry later'
    assert rows[1]['last_checked'] == '1750000000'
    assert rows[1]['in_stock'] == 'False'
    assert rows[1]['price'] == '0'
    assert rows[1]['currency'] == 'EUR'
    assert rows[0]['in_stock'] == ''
    assert len(datastore.data['watching']) == 3
    assert datastore.data['watching'][first]['last_error'] == 'HTTP 503, retry later'


def test_export_does_not_default_to_all_watches(client):
    datastore = client.application.config['DATASTORE']
    datastore.add_watch(url='https://example.com/private', extras={'paused': True})
    endpoint = url_for('ui.export_selected_watches')
    assert client.post(endpoint, data={'uuids': [' ', '']}).status_code == 400
    response = client.post(endpoint, data={'uuids': ['deleted-watch']})
    assert response.status_code == 200
    assert list(csv.DictReader(StringIO(response.data.decode('utf-8-sig')))) == []
    # The application's catch-all GET route returns 404 for POST-only form URLs.
    assert client.get(endpoint).status_code == 404


def test_export_requires_login_when_password_is_set(client, monkeypatch):
    settings = client.application.config['DATASTORE'].data['settings']['application']
    monkeypatch.setitem(settings, 'password', 'configured-password')
    response = client.post(url_for('ui.export_selected_watches'), data={'uuids': ['first']})
    assert response.status_code == 302
    assert '/login' in response.headers['Location']


def test_export_csrf_and_button(client, monkeypatch):
    datastore = client.application.config['DATASTORE']
    uuid = datastore.add_watch(url='https://example.com/watch', extras={'paused': True})
    monkeypatch.setitem(client.application.config, 'WTF_CSRF_ENABLED', True)
    endpoint = url_for('ui.export_selected_watches')
    assert client.post(endpoint, data={'uuids': [uuid]}).status_code == 400
    page = client.get(url_for('watchlist.index')).data.decode()
    assert 'id="checkbox-export"' in page
    assert f'formaction="{endpoint}"' in page
    token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    response = client.post(endpoint, data={'uuids': [uuid], 'csrf_token': token})
    assert response.status_code == 200
    assert 'https://example.com/watch' in response.data.decode()
