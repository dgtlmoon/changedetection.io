"""
Regex filter plugin for Jinja2 templates.

Provides regex_replace filter for pattern-based string replacements in templates.
"""
import os
import re
from loguru import logger

REGEX_TIMEOUT_SECONDS = int(os.getenv('REGEX_TIMEOUT_SECONDS', 10))  # Maximum time for a regex operation


def regex_replace(value: str, pattern: str, replacement: str = '', count: int = 0) -> str:
    """
    Replace occurrences of a regex pattern in a string.

    Security: Protected against ReDoS (Regular Expression Denial of Service) attacks:
    - Limits input value size to prevent excessive processing
    - Uses timeout mechanism to prevent runaway regex operations
    - Validates pattern complexity to prevent catastrophic backtracking

    Args:
        value: The input string to perform replacements on
        pattern: The regex pattern to search for
        replacement: The replacement string (default: '')
        count: Maximum number of replacements (0 = replace all, default: 0)

    Returns:
        String with replacements applied, or original value on error

    Example:
        {{ "hello world" | regex_replace("world", "universe") }}
        {{ diff | regex_replace("<td>([^<]+)</td><td>([^<]+)</td>", "Label1: \\1\\nLabel2: \\2") }}

    Security limits:
        - Maximum input size: 10MB
        - Maximum pattern length: 500 characters
        - Operation timeout: 10 seconds (REGEX_TIMEOUT_SECONDS env var)
        - Dangerous nested quantifier patterns are rejected
    """
    # Security limits
    MAX_INPUT_SIZE = 1024 * 1024 * 10 # 10MB max input size
    MAX_PATTERN_LENGTH = 500  # Maximum regex pattern length

    # Validate input sizes
    value_str = str(value)
    if len(value_str) > MAX_INPUT_SIZE:
        logger.warning(f"regex_replace: Input too large ({len(value_str)} bytes), truncating")
        value_str = value_str[:MAX_INPUT_SIZE]

    if len(pattern) > MAX_PATTERN_LENGTH:
        logger.warning(f"regex_replace: Pattern too long ({len(pattern)} chars), rejecting")
        return value_str

    # Check for potentially dangerous patterns (basic checks)
    # Nested quantifiers like (a+)+ can cause catastrophic backtracking
    dangerous_patterns = [
        r'\([^)]*\+[^)]*\)\+',  # (x+)+
        r'\([^)]*\*[^)]*\)\+',  # (x*)+
        r'\([^)]*\+[^)]*\)\*',  # (x+)*
        r'\([^)]*\*[^)]*\)\*',  # (x*)*
    ]

    for dangerous in dangerous_patterns:
        if re.search(dangerous, pattern):
            logger.warning(f"regex_replace: Potentially dangerous pattern detected: {pattern}")
            return value_str

    # Imported here, not at module level - nothing else loads 'regex' at startup and it costs ~2MB RSS
    # per instance, so only pay for it when a template actually uses this filter
    import regex

    try:
        # The 'regex' package enforces the timeout inside the matcher itself, so unlike
        # signal.alarm() it works in any thread (notifications are rendered in the
        # notification runner threads, previews in the Flask request threads)
        return regex.sub(pattern, replacement, value_str, count=count, timeout=REGEX_TIMEOUT_SECONDS)

    except TimeoutError:
        logger.error(f"regex_replace: Regex operation timed out - possible ReDoS attack. Pattern: {pattern}")
        return value_str
    except regex.error as e:
        logger.warning(f"regex_replace: Invalid regex pattern: {e}")
        return value_str
    except Exception as e:
        logger.error(f"regex_replace: Unexpected error: {e}")
        return value_str
