"""
Utility functions for RSS feed generation.
"""

from changedetectionio.jinja2_custom import render as jinja_render
from changedetectionio.notification.handler import apply_service_tweaks
from loguru import logger
import re


BAD_CHARS_REGEX = r'[\x00-\x08\x0B\x0C\x0E-\x1F]'


def scan_invalid_chars_in_rss(content):
    """
    Scan for invalid characters in RSS content.
    Returns True if invalid characters are found.
    """
    for match in re.finditer(BAD_CHARS_REGEX, content):
        i = match.start()
        bad_char = content[i]
        hex_value = f"0x{ord(bad_char):02x}"
        # Grab context
        start = max(0, i - 20)
        end = min(len(content), i + 21)
        context = content[start:end].replace('\n', '\\n').replace('\r', '\\r')
        logger.warning(f"Invalid char {hex_value} at pos {i}: ...{context}...")
        # First match is enough
        return True

    return False


def clean_entry_content(content):
    """
    Remove invalid characters from RSS content.
    """
    cleaned = re.sub(BAD_CHARS_REGEX, '', content)
    return cleaned


def generate_watch_guid(watch):
    """
    Generate a unique GUID for a watch RSS entry.
    """
    return f"{watch['uuid']}/{watch.last_changed}"

