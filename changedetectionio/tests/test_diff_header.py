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
    # The title is one line and ellipsizes when it outgrows the bar, so the
    # untruncated text has to stay reachable on hover.
    assert heading.get('title') == expected


def _seeded_diff_page(client, **extras):
    datastore = client.application.config['DATASTORE']
    extras.setdefault('paused', True)
    uuid = datastore.add_watch(url='https://example.com/releases', extras=extras)
    watch = datastore.data['watching'][uuid]
    watch.save_history_blob('First release', 1700000000, 'first')
    watch.save_history_blob('Second release', 1700000060, 'second')
    response = client.get(url_for('ui.ui_diff.diff_history_page', uuid=uuid))
    assert response.status_code == 200
    return BeautifulSoup(response.data, 'html.parser')


def test_diff_filters_toggle_degrades_without_javascript(client):
    """The diff options collapse into a popover, but only once diff-overview.js
    has taken them over: the toggle ships hidden and the fieldset ships inline
    and inside the form, so with scripting off the options are still reachable
    and still submit."""
    page = _seeded_diff_page(client)

    toggle = page.select_one('#diff-form #diff-filters-toggle')
    assert toggle is not None
    # Inside a form, anything but type=button submits it.
    assert toggle.get('type') == 'button'
    assert toggle.get('aria-expanded') == 'false'
    assert toggle.get('aria-controls') == 'diff-style'

    options = page.select_one('#diff-form #diff-style')
    assert options is not None
    assert options.get('hidden') is None
    assert page.select_one('#diff-form #diff-style #ignoreWhitespace') is not None


def test_diff_version_arrows_are_named(client):
    """Only the arrow glyphs are visible in the compact bar, so each link has to
    carry the wording itself rather than lean on text the CSS hides."""
    page = _seeded_diff_page(client)

    for element_id in ('btn-previous', 'btn-next'):
        link = page.select_one(f'#keyboard-nav #{element_id}')
        assert link is not None
        assert link.get('aria-label')
        assert link.get('title') == link.get('aria-label')
        label = link.select_one('.keyboard-nav-label')
        assert label is not None
        # The accessible name has to be the same word the hidden label shows, so
        # that it comes from a msgid the catalogs already translate rather than a
        # longer phrase invented for this bar that only screen readers ever hear.
        assert link.get('aria-label') == label.get_text(strip=True)


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
