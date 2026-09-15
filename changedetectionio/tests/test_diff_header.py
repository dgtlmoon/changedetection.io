from flask import url_for
from bs4 import BeautifulSoup
import pytest


@pytest.mark.parametrize('title,page_title,expected', [
    ('Release notes <script>alert(1)</script>', 'Fetched title', 'Release notes <script>alert(1)</script>'),
    ('', 'Fetched title', 'Fetched title'),
    ('', '', 'https://example.com/releases'),
])
def test_diff_header_watch_label(client, title, page_title, expected):
    """The top line of the menu names the watch, so the page does not print the
    same URL twice: the watch's own title when it has one, the fetched page title
    next, and the URL only when neither is set."""
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
    heading = page.select_one('.header .current-diff-url')
    assert heading.get_text(strip=True) == expected
    assert heading.find('script') is None
    # Clicking it still goes to the watched page - only the text changed.
    assert heading.get('href') == 'https://example.com/releases'
    # The separate heading this replaced is gone, so the bar is one row shorter.
    assert page.select_one('#diff-watch-title') is None
    assert page.select_one('#diff-header #diff-form') is not None
    assert page.select_one('#diff-header .tabs') is not None
    assert page.select_one('#diff-header #difference') is None
    assert 'Second release' in page.select_one('#difference').get_text()
    # The line is one line and fades out when it outgrows the bar, so the
    # untruncated text has to stay reachable on hover / long-press.
    assert expected in heading.get('title')


def test_diff_header_label_keeps_the_url_reachable(client):
    """A title covers the URL that used to be printed here, so the hover text has
    to carry both - otherwise the only way to read the URL is to follow it."""
    datastore = client.application.config['DATASTORE']
    uuid = datastore.add_watch(url='https://example.com/releases', extras={
        'title': 'Release notes', 'paused': True,
    })
    watch = datastore.data['watching'][uuid]
    watch.save_history_blob('First release', 1700000000, 'first')
    watch.save_history_blob('Second release', 1700000060, 'second')

    page = BeautifulSoup(client.get(url_for('ui.ui_diff.diff_history_page', uuid=uuid)).data,
                         'html.parser')
    link = page.select_one('.header .current-diff-url')
    hover = link.get('title')
    assert 'Release notes' in hover
    assert 'https://example.com/releases' in hover

    # Without a title the line already *is* the URL, so hover must not repeat it.
    untitled = datastore.add_watch(url='https://example.com/other', extras={'paused': True})
    other = datastore.data['watching'][untitled]
    other.save_history_blob('First', 1700000000, 'first')
    other.save_history_blob('Second', 1700000060, 'second')
    page = BeautifulSoup(client.get(url_for('ui.ui_diff.diff_history_page', uuid=untitled)).data,
                         'html.parser')
    link = page.select_one('.header .current-diff-url')
    assert link.get('title') == 'https://example.com/other'


def test_diff_header_heart_stays_in_the_markup(client):
    """The heart is folded away by a media query on this page, not removed from
    it - so it has to still be in the DOM. Its visibility is in diff.scss and
    cannot be seen from here."""
    datastore = client.application.config['DATASTORE']
    uuid = datastore.add_watch(url='https://example.com/releases', extras={'paused': True})
    watch = datastore.data['watching'][uuid]
    watch.save_history_blob('First release', 1700000000, 'first')
    watch.save_history_blob('Second release', 1700000060, 'second')

    page = BeautifulSoup(client.get(url_for('ui.ui_diff.diff_history_page', uuid=uuid)).data,
                         'html.parser')
    assert page.select_one('#heart-us') is not None


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


def test_scrollable_title_script_is_global(client):
    """The top line is a scroll container whose fades are maintained by JS. The
    restock difference page and the image-SSIM preview page both render that line
    and neither loads diff-overview.js, so the script belongs in base.html - which
    is what putting it on a page with no title line at all demonstrates."""
    datastore = client.application.config['DATASTORE']
    uuid = datastore.add_watch(url='https://example.com/releases', extras={'paused': True})
    watch = datastore.data['watching'][uuid]
    watch.save_history_blob('First release', 1700000000, 'first')
    watch.save_history_blob('Second release', 1700000060, 'second')

    def scripts(response):
        assert response.status_code == 200
        page = BeautifulSoup(response.data, 'html.parser')
        return page, {s['src'] for s in page.select('script[src]')}

    page, srcs = scripts(client.get(url_for('ui.ui_diff.diff_history_page', uuid=uuid)))
    assert page.select_one('.header .current-diff-url') is not None
    script = page.select_one('script[src*="scrollable-title.js"]')
    assert script is not None
    # Deferred, so jQuery and the markup both exist by the time it runs.
    assert script.has_attr('defer')

    # The watch overview has no title line, and still serves the script: that is
    # only true of a base.html script, and it is what the other pages rely on.
    overview, srcs = scripts(client.get(url_for('watchlist.index')))
    assert overview.select_one('.header .current-diff-url') is None
    assert any('scrollable-title.js' in src for src in srcs)
    assert not any('diff-overview.js' in src for src in srcs)
