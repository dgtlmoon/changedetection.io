from flask import url_for
from bs4 import BeautifulSoup
import pytest


@pytest.mark.parametrize('title,page_title,expected', [
    ('Release notes <script>alert(1)</script>', 'Fetched title', 'Release notes <script>alert(1)</script>'),
    ('', 'Fetched title', 'Fetched title'),
    ('', '', 'https://example.com/releases'),
])
def test_diff_header_watch_label(client, title, page_title, expected):
    datastore = client.application.config['DATASTORE']
    uuid = datastore.add_watch(url='https://example.com/releases', extras={
        'title': title, 'page_title': page_title, 'paused': True,
    })
    watch = datastore.data['watching'][uuid]
    watch.save_history_blob('First release', 1700000000, 'first')
    watch.save_history_blob('Second release', 1700000060, 'second')

    response = client.get(url_for('ui.ui_diff.diff_history_page', uuid=uuid))
    assert response.status_code == 200
    page = BeautifulSoup(response.data, 'html.parser')
    heading = page.select_one('#diff-header #diff-watch-title')
    assert heading.get_text() == expected
    assert heading.find('script') is None
    assert page.select_one('#diff-header #diff-form') is not None
    assert page.select_one('#diff-header .tabs') is not None
    assert page.select_one('#diff-header #difference') is None
    assert 'Second release' in page.select_one('#difference').get_text()


def test_difference_page_class_scopes_sticky_header(client):
    """The sticky top menu is styled off body.difference-page, so only the diff
    page may carry that class - the extract page shares the same blueprint."""
    datastore = client.application.config['DATASTORE']
    uuid = datastore.add_watch(url='https://example.com/releases', extras={'paused': True})
    watch = datastore.data['watching'][uuid]
    watch.save_history_blob('First release', 1700000000, 'first')
    watch.save_history_blob('Second release', 1700000060, 'second')

    diff = BeautifulSoup(client.get(url_for('ui.ui_diff.diff_history_page', uuid=uuid)).data,
                         'html.parser')
    assert 'difference-page' in diff.select_one('body').get('class')

    extract = client.get(url_for('ui.ui_diff.diff_history_page_extract_GET', uuid=uuid))
    assert extract.status_code == 200
    assert 'difference-page' not in BeautifulSoup(extract.data, 'html.parser').select_one('body').get('class')
