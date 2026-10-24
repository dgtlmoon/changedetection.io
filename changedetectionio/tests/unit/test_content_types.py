#!/usr/bin/env python3

from changedetectionio.content_types import binary_rule, kept_artifact_extensions


def test_known_content_types():
    rule = binary_rule('application/pdf')
    assert rule['ext'] == 'pdf'
    assert rule['keep_last_versions'] == 2
    assert rule['to_text'] == 'pdftohtml'

    rule = binary_rule('application/x-msi')
    assert rule['ext'] == 'msi'
    assert rule['keep_last_versions'] == 0

    rule = binary_rule('image/jpeg; charset=binary')
    assert rule['ext'] == 'jpg'
    assert rule['use_as_screenshot'] is True


def test_text_types_are_not_binary():
    for content_type in ('text/html; charset=utf-8', 'application/json', 'text/plain', 'application/rss+xml', None):
        assert binary_rule(content_type, url='https://example.com/page') is None


def test_generic_content_type_uses_the_url():
    assert binary_rule('application/octet-stream', url='https://example.com/download/driver.MSI?v=2')['ext'] == 'msi'
    assert binary_rule('', url='https://example.com/setup.exe')['ext'] == 'exe'
    # Only for content types that don't say what the file is
    assert binary_rule('text/html', url='https://example.com/setup.exe') is None
    assert binary_rule('application/octet-stream', url='https://example.com/download') is None


def test_kept_artifacts():
    kept = kept_artifact_extensions()
    assert kept['html.br'] == 2
    assert kept['pdf'] == 2
    assert 'msi' not in kept
