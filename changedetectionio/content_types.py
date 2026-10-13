"""How non-HTML (binary) responses are treated.

One entry per content type:
    ext                 file extension for a kept original, and to recognise the type by URL when
                        the server only says application/octet-stream (or nothing)
    keep_last_versions  how many original files to keep alongside the history (0 = none, only
                        the checksum ends up in the snapshot)
    max_keep_bytes      originals bigger than this are not kept (the checksum still is)
    to_text             converter for extracting text into the snapshot, if any
    use_as_screenshot   the file itself is the screenshot (images)

The last fetched HTML is kept the same way, see HTML_ARTIFACT.
"""

import os
from urllib.parse import urlparse

MB = 1024 * 1024

BINARY_CONTENT_TYPES = {
    'application/pdf': {'ext': 'pdf', 'keep_last_versions': 2, 'max_keep_bytes': 20 * MB, 'to_text': 'pdftohtml'},

    'image/jpeg': {'ext': 'jpg', 'use_as_screenshot': True},
    'image/png': {'ext': 'png', 'use_as_screenshot': True},
    'image/gif': {'ext': 'gif', 'use_as_screenshot': True},
    'image/webp': {'ext': 'webp', 'use_as_screenshot': True},

    'application/x-msi': {'ext': 'msi'},
    'application/x-ms-installer': {'ext': 'msi'},
    'application/x-msdownload': {'ext': 'exe'},
    'application/vnd.microsoft.portable-executable': {'ext': 'exe'},
    'application/x-msdos-program': {'ext': 'exe'},
    'application/x-apple-diskimage': {'ext': 'dmg'},
    'application/vnd.android.package-archive': {'ext': 'apk'},
    'application/vnd.debian.binary-package': {'ext': 'deb'},
    'application/x-rpm': {'ext': 'rpm'},
    'application/java-archive': {'ext': 'jar'},
    'application/zip': {'ext': 'zip'},
    'application/x-7z-compressed': {'ext': '7z'},
    'application/x-rar-compressed': {'ext': 'rar'},
    'application/vnd.rar': {'ext': 'rar'},
    'application/gzip': {'ext': 'gz'},
    'application/x-gzip': {'ext': 'gz'},
    'application/x-tar': {'ext': 'tar'},
    'application/x-xz': {'ext': 'xz'},
    'application/x-bzip2': {'ext': 'bz2'},
    'application/x-iso9660-image': {'ext': 'iso'},
}

RULE_DEFAULTS = {'keep_last_versions': 0, 'max_keep_bytes': 0, 'to_text': None, 'use_as_screenshot': False}

# Content types that say nothing about what the file is, so the URL's extension decides
GENERIC_BINARY_CONTENT_TYPES = ('application/octet-stream', 'binary/octet-stream', 'application/x-download', '')

# The last fetched HTML, kept per history entry as {timestamp}.html.br
HTML_ARTIFACT = {'ext': 'html.br', 'keep_last_versions': 2}


def _with_defaults(content_type, rule):
    return {**RULE_DEFAULTS, **rule, 'content_type': content_type}


_BY_EXT = {}
for _content_type, _rule in BINARY_CONTENT_TYPES.items():
    _BY_EXT.setdefault(_rule['ext'], _with_defaults(_content_type, _rule))


def binary_rule(content_type, url=None):
    """The rule for this response, or None when it isn't a binary type we know about."""
    content_type = (content_type or '').split(';')[0].strip().lower()
    if content_type in BINARY_CONTENT_TYPES:
        return _with_defaults(content_type, BINARY_CONTENT_TYPES[content_type])

    if url and content_type in GENERIC_BINARY_CONTENT_TYPES:
        ext = os.path.splitext(urlparse(url).path)[1].lstrip('.').lower()
        if ext in _BY_EXT:
            return _BY_EXT[ext]

    return None


def kept_artifact_extensions():
    """{extension: how many to keep} for every artifact type that is kept per history entry."""
    keep = {HTML_ARTIFACT['ext']: HTML_ARTIFACT['keep_last_versions']}
    for rule in BINARY_CONTENT_TYPES.values():
        if rule.get('keep_last_versions'):
            keep[rule['ext']] = max(keep.get(rule['ext'], 0), rule['keep_last_versions'])
    return keep
