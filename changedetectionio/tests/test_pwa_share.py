#!/usr/bin/env python3
"""
Android Web Share Target hand-off.

The manifest points share_target at the watch list itself, so sharing a page from any Android
app arrives as GET /?pwa_preset_url=... and prefills the quick-add form's URL field. Everything
after that is the form that was already there - the processor radios pick the mode, the LLM
intent box is right underneath, and the watch is only created by the form's POST.

That "GET never creates anything" property is the reason this is safe to have on a plain
navigation that any app on the phone can trigger.
"""

from changedetectionio.blueprint.pwa.service import is_share, pwa_preset_url


def test_extracts_the_url_param():
    assert pwa_preset_url({'pwa_preset_url': 'https://example.com/a.html'}) == 'https://example.com/a.html'
    assert pwa_preset_url({'pwa_preset_url': '  https://example.com/a.html  '}) == 'https://example.com/a.html'


def test_digs_the_url_out_of_shared_text():
    """Most Android apps put the link in the text body rather than the url field."""
    assert pwa_preset_url({
        'pwa_preset_text': 'Check this out https://example.com/deal?id=3 - cheap!'
    }) == 'https://example.com/deal?id=3'

    assert pwa_preset_url({
        'pwa_preset_title': 'Look https://example.com/t'
    }) == 'https://example.com/t'

    # An explicit url param always wins over scraping prose
    assert pwa_preset_url({
        'pwa_preset_url': 'https://example.com/real',
        'pwa_preset_text': 'https://example.com/decoy',
    }) == 'https://example.com/real'


def test_schemeless_gets_a_scheme():
    """A share sheet hands over plenty of bare hostnames."""
    assert pwa_preset_url({'pwa_preset_url': 'foobar.com/blah.html'}) == 'http://foobar.com/blah.html'


def test_trailing_sentence_punctuation_is_not_part_of_the_url():
    """The regex this replaced took the full stop with it, and the prefilled URL 404d -
    on the one attempt most people will ever give this."""
    assert pwa_preset_url({'pwa_preset_text': 'have a look at https://example.com/page.'}) \
        == 'https://example.com/page'
    assert pwa_preset_url({'pwa_preset_text': '(see https://example.com/x) ok'}) \
        == 'https://example.com/x'


def test_brackets_belonging_to_the_url_are_kept():
    assert pwa_preset_url({'pwa_preset_text': 'https://en.wikipedia.org/wiki/Foo_(bar) end'}) \
        == 'https://en.wikipedia.org/wiki/Foo_(bar)'


def test_an_explicit_http_url_is_taken_verbatim():
    """Don't let the linkifier trim a trailing character an app deliberately sent."""
    messy = 'https://www.amazon.de/dp/B08N5WRWNW?ref_=foo&th=1,'
    assert pwa_preset_url({'pwa_preset_url': messy}) == messy


def test_non_web_links_are_not_offered():
    """Prefilling any of these is just noise in a box that only wants a web page."""
    assert pwa_preset_url({'pwa_preset_text': 'mail me at contact@example.com'}) == ''
    assert pwa_preset_url({'pwa_preset_text': 'ftp://files.example.com/x'}) == ''
    assert pwa_preset_url({'pwa_preset_text': 'check //example.com/proto-relative'}) == ''
    for hostile in ('javascript:alert(1)', 'data:text/html;base64,PHNjcmlwdD4=',
                    'file:///etc/passwd', 'JavaScript:alert(1)'):
        assert pwa_preset_url({'pwa_preset_url': hostile}) == '', f"{hostile} was let through"


def test_a_plain_icon_launch_is_not_a_share():
    """start_url and share_target.action are the same URL, so the params are the only
    signal - and a home screen launch must not produce share UI."""
    assert is_share({}) is False
    assert is_share({'tag': 'something', 'q': 'search'}) is False
    assert is_share({'pwa_preset_text': 'shared a photo, no link'}) is True


def test_share_with_no_link_says_so(client, live_server):
    res = client.get('/?pwa_preset_text=just+some+text+with+no+link', follow_redirects=True)
    assert res.status_code == 200
    assert b'Nothing shareable was found' in res.data


def test_plain_launch_is_quiet(client, live_server):
    assert b'Nothing shareable was found' not in client.get('/', follow_redirects=True).data


def test_nothing_shared_is_not_an_error():
    assert pwa_preset_url({}) == ''
    assert pwa_preset_url({'pwa_preset_url': '', 'pwa_preset_text': 'no link in here'}) == ''


def test_share_prefills_the_quick_add_form(client, live_server):
    res = client.get('/?pwa_preset_url=https://example.com/shared-page.html')
    assert res.status_code == 200
    assert b'value="https://example.com/shared-page.html"' in res.data, (
        "shared URL did not reach the quick-add form's URL field"
    )


def test_share_from_text_prefills_the_quick_add_form(client, live_server):
    res = client.get('/?pwa_preset_text=have+a+look+https%3A%2F%2Fexample.com%2Ffrom-text+ok')
    assert res.status_code == 200
    assert b'value="https://example.com/from-text"' in res.data


def test_share_does_not_create_a_watch(client, live_server):
    """A GET that any installed app can trigger must not be able to add anything."""
    before = client.get('/').data

    client.get('/?pwa_preset_url=https://example.com/not-added.html')

    after = client.get('/').data
    assert b'https://example.com/not-added.html' not in after
    assert before.count(b'watch-table') == after.count(b'watch-table')


def test_service_worker_is_served_from_the_root(client, live_server):
    """A worker can only control paths at or below its own URL. From /static/js/ its scope
    would be /static/js/, no WebAPK would be built, and the share sheet entry never appears."""
    res = client.get('/sw.js')
    assert res.status_code == 200
    assert res.headers['Content-Type'].startswith('text/javascript')
    assert b"addEventListener('fetch'" in res.data, (
        "a fetch handler is the part Chrome's install criteria have wanted"
    )
    assert 'no-cache' in res.headers['Cache-Control'], (
        "a hard-cached worker script can't be updated"
    )


def test_share_survives_the_login_redirect(app, client, live_server, datastore_path):
    """First run on a password-protected instance: install, share, get bounced to login.

    unauthorized_handler used request.path, which drops the query string - so after logging
    in the user landed on an empty watch list and the URL they just shared was gone. People
    try this once.
    """
    with app.test_client(use_cookies=True) as c:
        res = c.post(
            "/settings",
            data={"application-password": "foobar",
                  "requests-time_between_check-minutes": 180,
                  'application-fetch_backend': "html_requests"},
            follow_redirects=True
        )
        assert b"Password protection enabled." in res.data

        try:
            res = c.get('/?pwa_preset_url=https://example.com/shared.html')
            assert res.status_code == 302
            assert 'pwa_preset_url' in res.headers['Location'], (
                f"shared URL dropped on the way to login: {res.headers['Location']}"
            )

            # ...and it's still there once the login page renders it back into its form
            res = c.get(res.headers['Location'])
            assert b'pwa_preset_url' in res.data
        finally:
            c.post("/settings", data={"application-removepassword_button": "Remove password"},
                   follow_redirects=True)
