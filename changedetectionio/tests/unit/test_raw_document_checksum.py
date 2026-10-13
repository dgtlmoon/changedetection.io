#!/usr/bin/env python3

import hashlib
from types import SimpleNamespace

from changedetectionio.processors.base import difference_detection_processor


def _checksum(content, raw_content):
    processor = object.__new__(difference_detection_processor)
    processor.fetcher = SimpleNamespace(content=content, raw_content=raw_content)
    return processor.get_raw_document_checksum()


def test_html_uses_content():
    # requests sets raw_content for every page, but non-PDF checksums must stay on .content
    html = '<html><body>hello</body></html>'
    assert _checksum(html, html.encode('utf-8') + b'\n') == hashlib.md5(html.encode('utf-8')).hexdigest()
    assert _checksum(html, None) == hashlib.md5(html.encode('utf-8')).hexdigest()


def test_pdf_uses_raw_content():
    pdf = b'%PDF-1.4\nsome pdf body'
    viewer_html = '<html><body><embed type="application/pdf"></body></html>'
    # The browser's PDF viewer HTML is the same for every version, the PDF bytes are what count
    assert _checksum(viewer_html, pdf) == hashlib.md5(pdf).hexdigest()
    assert _checksum(viewer_html, pdf) != _checksum(viewer_html, pdf + b'changed')


def test_nothing_fetched():
    assert _checksum(None, None) is None
