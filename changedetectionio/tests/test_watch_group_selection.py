from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup
from flask import url_for


def add_group(client, live_server, title):
    token = live_server.app.config['DATASTORE'].data['settings']['application']['api_access_token']
    response = client.post(
        url_for('tag'),
        json={'title': title},
        headers={'x-api-key': token},
    )
    assert response.status_code == 201
    return response.json['uuid']


def active_group(response, title):
    assert response.status_code == 200
    soup = BeautifulSoup(response.data, 'html.parser')
    assert soup.select_one('#tag-lister a.active').get_text(strip=True) == title
    return soup


def test_group_survives_returning_home(client, live_server):
    group = add_group(client, live_server, 'Remember me')
    active_group(client.get(url_for('watchlist.index', tag=group)), 'Remember me')
    response = client.get(url_for('watchlist.index', q='needle', unread=1))
    assert response.status_code == 302
    query = parse_qs(urlparse(response.location).query)
    assert query['tag'] == [group]
    assert query['q'] == ['needle']
    assert query['unread'] == ['1']
    active_group(client.get(response.location), 'Remember me')


def test_all_link_explicitly_clears_remembered_group(client, live_server):
    group = add_group(client, live_server, 'Selected group')
    soup = active_group(client.get(url_for('watchlist.index', tag=group)), 'Selected group')
    all_link = soup.select_one('#tag-all')['href']
    assert parse_qs(urlparse(all_link).query, keep_blank_values=True)['tag'] == ['']
    active_group(client.get(all_link, follow_redirects=True), 'All')
    active_group(client.get(url_for('watchlist.index'), follow_redirects=True), 'All')


def test_new_group_selection_replaces_previous_group(client, live_server):
    first = add_group(client, live_server, 'First')
    second = add_group(client, live_server, 'Second')
    client.get(url_for('watchlist.index', tag=first))
    client.get(url_for('watchlist.index', tag=second))
    active_group(client.get(url_for('watchlist.index'), follow_redirects=True), 'Second')


def test_deleted_group_does_not_cause_a_redirect_loop(client, live_server):
    group = add_group(client, live_server, 'Deleted')
    client.get(url_for('watchlist.index', tag=group))
    client.post(url_for('tags.delete_all'))
    active_group(client.get(url_for('watchlist.index')), 'All')


def test_legacy_rss_link_ignores_remembered_group(client, live_server):
    group = add_group(client, live_server, 'UI only')
    client.get(url_for('watchlist.index', tag=group))
    response = client.get(url_for('watchlist.index', rss='true'))
    assert response.status_code == 302
    assert 'tag' not in parse_qs(urlparse(response.location).query)
