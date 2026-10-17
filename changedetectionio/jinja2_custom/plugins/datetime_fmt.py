"""
Unix-timestamp conversion filter plugin for Jinja2 templates.

Provides the ``unixtime`` filter, which converts a Unix timestamp (seconds,
milliseconds or microseconds) into a human-readable, strftime-formatted string.

Requested in #3641: API/JSON-style monitored pages often expose values such as
``last_battle_at: 1759188682`` and notifications printed the raw integer.
"""
import datetime
import os
import re
import typing as t

from loguru import logger

# Bound the size of input we will parse, mirroring the defensive limits used by
# the other Jinja plugins. A notification token should never be multi-MB.
MAX_INPUT_SIZE = 1024 * 1024  # 1 MB

# Default output format (overridable per call) and default timezone.
DEFAULT_FORMAT = "%Y-%m-%d %H:%M:%S %Z"

# A bare 10+ digit run is enough to locate a timestamp embedded in prose such
# as "last_battle_at: 1759188682" without accepting unrelated small numbers.
_TIMESTAMP_RE = re.compile(r"-?\d{9,}")


def _default_tzname() -> str:
    return os.getenv("TZ", "UTC").strip() or "UTC"


def _resolve_timezone(tz_name: t.Optional[str]):
    """Return a tzinfo for tz_name, defaulting to UTC without third-party deps."""
    name = (tz_name or _default_tzname()).strip()
    if name.upper() in ("", "UTC"):
        return datetime.timezone.utc
    # datetime.timezone only supports fixed offsets; resolve common named zones
    # via the UTC-offset environment when available. Avoid importing zoneinfo on
    # runtimes without the tz database by falling back to UTC.
    try:
        from zoneinfo import ZoneInfo  # stdlib on Python 3.9+

        return ZoneInfo(name)
    except Exception:
        return datetime.timezone.utc


def _coerce_timestamp(raw: t.Any) -> t.Optional[int]:
    """
    Extract a Unix timestamp in seconds from ints, floats, numeric strings or
    prose containing one. Millisecond (13-digit) and microsecond (16-digit)
    values are normalised to seconds. Returns None when no value is usable.
    """
    if raw is None:
        return None

    if isinstance(raw, bool):  # bool is a subclass of int — never treat as ts
        return None

    if isinstance(raw, (int, float)):
        value = int(raw)
    else:
        text = str(raw)
        if len(text) > MAX_INPUT_SIZE:
            logger.warning("unixtime: input too large (%d bytes), truncating", len(text))
            text = text[:MAX_INPUT_SIZE]
        match = _TIMESTAMP_RE.search(text)
        if not match:
            return None
        value = int(match.group(0))

    if abs(value) >= 1_000_000_000_000_000:      # microseconds
        value //= 1_000_000
    elif abs(value) >= 1_000_000_000_000:        # milliseconds
        value //= 1_000
    # Anything >= ~1e9 is plausible as seconds. Smaller 9-digit values
    # (e.g. 999999999 ≈ 2001) are still accepted by the regex.
    return value


def unixtime(
    value: t.Any,
    fmt: str = DEFAULT_FORMAT,
    tz_name: t.Optional[str] = None,
) -> t.Any:
    """
    Format a Unix timestamp as a human-readable datetime.

    Args:
        value: timestamp as int/float/string, or text containing one. Seconds,
            milliseconds and microseconds are all accepted.
        fmt: ``strftime`` format string (default ``%Y-%m-%d %H:%M:%S %Z``).
        tz_name: timezone name (default: ``$TZ`` or UTC).

    Returns:
        The formatted datetime string. On any failure (missing/invalid value or
        format) the original value is returned unchanged, so a notification
        never crashes and simply falls back to the raw token.

    Examples:
        {{ triggered_text | unixtime }}
        {{ triggered_text | unixtime("%d.%m.%Y %H:%M") }}
        {{ triggered_text | unixtime("%d.%m.%Y %H:%M", "Europe/Berlin") }}
    """
    seconds = _coerce_timestamp(value)
    if seconds is None:
        return value

    try:
        tzinfo = _resolve_timezone(tz_name)
        dt = datetime.datetime.fromtimestamp(seconds, tz=tzinfo)
        return dt.strftime(fmt)
    except (ValueError, OSError, OverflowError) as e:
        # Bad format string or out-of-range timestamp — keep the raw token.
        logger.warning("unixtime: could not format value %r (%s)", value, e)
        return value
