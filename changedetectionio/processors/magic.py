# When to apply the 'cdata to real HTML' hack
# @todo Some heuristic check instead? first and last bytes? maybe some new def that gets header+first 200 bytes? then we can unittest
RSS_XML_CONTENT_TYPES = [
    "application/rss+xml",
    "application/rdf+xml",
    "text/xml",
    "application/xml",
    "application/atom+xml",
    "text/rss+xml",  # rare, non-standard
    "application/x-rss+xml",  # legacy (older feed software)
    "application/x-atom+xml",  # legacy (older Atom)
]

# JSON Content-types
# @todo Some heuristic check instead? first and last bytes? maybe some new def that gets header+first 200 bytes? then we can unittest
JSON_CONTENT_TYPES = [
    "application/activity+json",
    "application/feed+json",
    "application/json",
    "application/ld+json",
    "application/vnd.api+json",
]

# CSV Content-types
CSV_CONTENT_TYPES = [
    "text/csv",
    "application/csv",
]

# Generic XML Content-types (non-RSS/Atom)
XML_CONTENT_TYPES = [
    "text/xml",
    "application/xml",
]

# YAML Content-types
YAML_CONTENT_TYPES = [
    "text/yaml",
    "text/x-yaml",
    "application/yaml",
    "application/x-yaml",
]

HTML_PATTERNS = ['<!doctype html', '<html', '<head', '<body', '<script', '<iframe', '<div']

import re
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

    def __init__(self, content_header, content):

        magic_content_header = content_header
        test_content = content[:200].lower().strip()

        # Remove whitespace between < and tag name for robust detection (handles '< html', '<\nhtml', etc.)
        test_content_normalized = re.sub(r'<\s+', '<', test_content)

        # Magic will sometimes call text/plain as text/html!
        magic_result = None
        try:
            import magic
            mime = magic.from_buffer(content[:200], mime=True) # Send the original content
            logger.debug(f"Guessing mime type, original content_type '{content_header}', mime type detected '{mime}'")
            if mime and "/" in mime:
                magic_result = mime
                # Trust magic for non-text types immediately
                if mime not in ['text/html', 'text/plain']:
                    magic_content_header = mime

        except Exception as e:
            logger.error(f"Error getting a more precise mime type from 'magic' library ({str(e)}), using content-based detection")

        # Content-based detection (most reliable for text formats)
        # Check for HTML patterns first - if found, override magic's text/plain
        has_html_patterns = any(p in test_content_normalized for p in HTML_PATTERNS)

        if has_html_patterns:
            self.is_html = True
            # Override magic if it said text/plain
            if magic_result == 'text/plain':
                logger.debug(f"Overriding magic's text/plain with HTML detection based on content patterns")
                magic_content_header = 'text/html'
        # If magic says text/plain and we found no HTML patterns, trust it
        elif magic_result == 'text/plain':
            self.is_plaintext = True
            logger.debug(f"Trusting magic's text/plain result (no HTML patterns detected)")
        elif '<rss' in test_content_normalized or '<feed' in test_content_normalized:
            self.is_rss = True
        elif test_content_normalized.startswith('<?xml'):
            # Generic XML that's not RSS/Atom (RSS/Atom checked above)
            self.is_xml = True
        elif test_content.startswith('{') or test_content.startswith('['):
            self.is_json = True
        elif test_content.startswith('---') or test_content.startswith('%yaml'):
            # YAML typically starts with --- or %YAML directive
            self.is_yaml = True
        elif '%pdf-1' in test_content:
            self.is_pdf = True
        # Check headers for types we didn't detect by content
        elif any(s in content_header for s in RSS_XML_CONTENT_TYPES) or any(s in magic_content_header for s in RSS_XML_CONTENT_TYPES):
            self.is_rss = True
        elif any(s in content_header for s in JSON_CONTENT_TYPES) or any(s in magic_content_header for s in JSON_CONTENT_TYPES):
            self.is_json = True
        elif any(s in content_header for s in CSV_CONTENT_TYPES) or any(s in magic_content_header for s in CSV_CONTENT_TYPES):
            self.is_csv = True
        elif any(s in content_header for s in XML_CONTENT_TYPES) or any(s in magic_content_header for s in XML_CONTENT_TYPES):
            # Only mark as generic XML if not already detected as RSS
            if not self.is_rss:
                self.is_xml = True
        elif any(s in content_header for s in YAML_CONTENT_TYPES) or any(s in magic_content_header for s in YAML_CONTENT_TYPES):
            self.is_yaml = True
        elif 'pdf' in magic_content_header:
            self.is_pdf = True
        # Only trust magic for 'text' if no other patterns matched
        elif 'text' in magic_content_header:
            self.is_plaintext = True

