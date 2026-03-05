#!/usr/bin/env python3
# coding=utf-8

import hashlib
import time
from flask import url_for
from .util import live_server_setup, wait_for_all_checks, extract_UUID_from_client
import pytest
import os





def test_surrogate_characters_in_content_are_sanitized():
    """Lone surrogates can appear in requests' r.text when a server returns malformed/mixed-encoding
    content. Without sanitization, encoding to UTF-8 raises UnicodeEncodeError.
    See: https://github.com/dgtlmoon/changedetection.io/issues/3952
    """
    content_with_surrogate = '<html><body>Hello \udcad World</body></html>'

    # Confirm the raw problem exists
    with pytest.raises(UnicodeEncodeError):
        content_with_surrogate.encode('utf-8')

    # Our fix: sanitize after fetcher.run() in processors/base.py call_browser()
    sanitized = content_with_surrogate.encode('utf-8', errors='replace').decode('utf-8')
    assert 'Hello' in sanitized
    assert 'World' in sanitized
    assert '\udcad' not in sanitized

    # Checksum computation (processors/base.py get_raw_document_checksum) must not crash
    hashlib.md5(sanitized.encode('utf-8')).hexdigest()


def test_utf8_content_without_charset_header(client, live_server, datastore_path):
    """Server returns UTF-8 content but no charset in Content-Type header.
    chardet can misdetect such pages as UTF-7 (Python 3.14 then produces surrogates).
    Our fix tries UTF-8 first before falling back to chardet.
    See: https://github.com/dgtlmoon/changedetection.io/issues/3952
    """
    from .util import write_test_file_and_sync
    # UTF-8 encoded content with non-ASCII chars - no charset will be in the header
    html = '<html><body><p>Español</p><p>Français</p><p>日本語</p></body></html>'
    write_test_file_and_sync(os.path.join(datastore_path, "endpoint-content.txt"), html.encode('utf-8'), mode='wb')

    test_url = url_for('test_endpoint', content_type="text/html", _external=True)
    client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    res = client.get(url_for("ui.ui_preview.preview_page", uuid="first"), follow_redirects=True)
    # Should decode correctly as UTF-8, not produce mojibake (EspaÃ±ol) or replacement chars
    assert 'Español'.encode('utf-8') in res.data
    assert 'Français'.encode('utf-8') in res.data
    assert '日本語'.encode('utf-8') in res.data


def test_shiftjis_content_without_charset_header(client, live_server, datastore_path):
    """Server returns Shift-JIS encoded content with no charset header.
    UTF-8 decode will fail, so we fall back to chardet which should detect Shift-JIS.
    """
    from .util import write_test_file_and_sync
    japanese_text = '日本語のページ'
    html = f'<html><body><p>{japanese_text}</p></body></html>'
    write_test_file_and_sync(os.path.join(datastore_path, "endpoint-content.txt"), html.encode('shift_jis'), mode='wb')

    test_url = url_for('test_endpoint', content_type="text/html", _external=True)
    client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    res = client.get(url_for("ui.ui_preview.preview_page", uuid="first"), follow_redirects=True)
    # chardet should detect Shift-JIS and decode correctly to Unicode
    assert japanese_text.encode('utf-8') in res.data


def set_html_response(datastore_path):
    test_return_data = """
<html><body><span class="nav_second_img_text">
                  &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;铸大国重器，挺制造脊梁，致力能源未来，赋能美好生活。
                                  </span>
</body></html>
    """
    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(test_return_data)
    return None


# In the case the server does not issue a charset= or doesnt have content_type header set
def test_check_encoding_detection(client, live_server, measure_memory_usage, datastore_path):
    set_html_response(datastore_path=datastore_path)

    # Add our URL to the import page
    test_url = url_for('test_endpoint', content_type="text/html", _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    wait_for_all_checks(client)


    # Content type recording worked
    uuid = next(iter(live_server.app.config['DATASTORE'].data['watching']))
    assert live_server.app.config['DATASTORE'].data['watching'][uuid]['content-type'] == "text/html"

    res = client.get(
        url_for("ui.ui_preview.preview_page", uuid="first"),
        follow_redirects=True
    )

    # Should see the proper string
    assert "铸大国重".encode('utf-8') in res.data
    # Should not see the failed encoding
    assert b'\xc2\xa7' not in res.data


# In the case the server does not issue a charset= or doesnt have content_type header set
def test_check_encoding_detection_missing_content_type_header(client, live_server, measure_memory_usage, datastore_path):
    set_html_response(datastore_path=datastore_path)

    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    wait_for_all_checks(client)

    res = client.get(
        url_for("ui.ui_preview.preview_page", uuid="first"),
        follow_redirects=True
    )

    # Should see the proper string
    assert "铸大国重".encode('utf-8') in res.data
    # Should not see the failed encoding
    assert b'\xc2\xa7' not in res.data
