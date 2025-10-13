"""
Content Type Detection and Stream Classification

This module provides intelligent content-type detection for changedetection.io.
It addresses the common problem where HTTP Content-Type headers are missing, incorrect,
or too generic, which would otherwise cause the wrong processor to be used.

The guess_stream_type class combines:
1. HTTP Content-Type headers (when available and reliable)
2. Python-magic library for MIME detection (analyzing actual file content)
3. Content-based pattern matching for text formats (HTML tags, XML declarations, etc.)

This multi-layered approach ensures accurate detection of RSS feeds, JSON, HTML, PDF,
plain text, CSV, YAML, and XML formats - even when servers provide misleading headers.

Used by: processors/text_json_diff/processor.py and other content processors
"""

# When to apply the 'cdata to real HTML' hack
RSS_XML_CONTENT_TYPES = [
    "application/rss+xml",
    "application/rdf+xml",
    "application/atom+xml",
    "text/rss+xml",  # rare, non-standard
    "application/x-rss+xml",  # legacy (older feed software)
    "application/x-atom+xml",  # legacy (older Atom)
]

# JSON Content-types
JSON_CONTENT_TYPES = [
    "application/activity+json",
    "application/feed+json",
    "application/json",
    "application/ld+json",
    "application/vnd.api+json",
]


# Generic XML Content-types (non-RSS/Atom)
XML_CONTENT_TYPES = [
    "text/xml",
    "application/xml",
]

HTML_PATTERNS = ['<!doctype html', '<html', '<head', '<body', '<script', '<iframe', '<div']

from loguru import logger

class guess_stream_type():
    is_pdf = False
    is_json = False
    is_html = False
    is_plaintext = False
    is_rss = False
    is_csv = False
    is_xml = False  # Generic XML, not RSS/Atom
    is_yaml = False

    def __init__(self, http_content_header, content):
        import re
        magic_content_header = http_content_header
        test_content = content[:200].lower().strip()

        # Remove whitespace between < and tag name for robust detection (handles '< html', '<\nhtml', etc.)
        test_content_normalized = re.sub(r'<\s+', '<', test_content)

        # Use puremagic for lightweight MIME detection (saves ~14MB vs python-magic)
        magic_result = None
        try:
            import puremagic

            # puremagic needs bytes, so encode if we have a string
            content_bytes = content[:200].encode('utf-8') if isinstance(content, str) else content[:200]

            # puremagic returns a list of PureMagic objects with confidence scores
            detections = puremagic.magic_string(content_bytes)
            if detections:
                # Get the highest confidence detection
                mime = detections[0].mime_type
                logger.debug(f"Guessing mime type, original content_type '{http_content_header}', mime type detected '{mime}'")
                if mime and "/" in mime:
                    magic_result = mime
                    # Ignore generic/fallback mime types
                    if mime in ['application/octet-stream', 'application/x-empty', 'binary']:
                        logger.debug(f"Ignoring generic mime type '{mime}' from puremagic library")
                    # Trust puremagic for non-text types immediately
                    elif mime not in ['text/html', 'text/plain']:
                        magic_content_header = mime

        except Exception as e:
            logger.error(f"Error getting a more precise mime type from 'puremagic' library ({str(e)}), using content-based detection")

        # Content-based detection (most reliable for text formats)
        # Check for HTML patterns first - if found, override magic's text/plain
        has_html_patterns = any(p in test_content_normalized for p in HTML_PATTERNS)

        # Always trust headers first
        if 'text/plain' in http_content_header:
            self.is_plaintext = True
        if any(s in http_content_header for s in RSS_XML_CONTENT_TYPES):
            self.is_rss = True
        elif any(s in http_content_header for s in JSON_CONTENT_TYPES):
            self.is_json = True
        elif 'pdf' in magic_content_header:
            self.is_pdf = True
        elif has_html_patterns or http_content_header == 'text/html':
            self.is_html = True
        elif any(s in magic_content_header for s in JSON_CONTENT_TYPES):
            self.is_json = True
        # magic will call a rss document 'xml'
        # Rarely do endpoints give the right header, usually just text/xml, so we check also for <rss
        # This also triggers the automatic CDATA text parser so the RSS goes back a nice content list
        elif '<rss' in test_content_normalized or '<feed' in test_content_normalized or any(s in magic_content_header for s in RSS_XML_CONTENT_TYPES) or '<rdf:' in test_content_normalized:
            self.is_rss = True
        elif any(s in http_content_header for s in XML_CONTENT_TYPES):
            # Only mark as generic XML if not already detected as RSS
            if not self.is_rss:
                self.is_xml = True
        elif test_content_normalized.startswith('<?xml') or any(s in magic_content_header for s in XML_CONTENT_TYPES):
            # Generic XML that's not RSS/Atom (RSS/Atom checked above)
            self.is_xml = True
        elif '%pdf-1' in test_content:
            self.is_pdf = True
        elif http_content_header.startswith('text/'):
            self.is_plaintext = True
        # Only trust magic for 'text' if no other patterns matched
        elif 'text' in magic_content_header:
            self.is_plaintext = True
        # If magic says text/plain and we found no HTML patterns, trust it
        elif magic_result == 'text/plain':
            self.is_plaintext = True
            logger.debug(f"Trusting magic's text/plain result (no HTML patterns detected)")

