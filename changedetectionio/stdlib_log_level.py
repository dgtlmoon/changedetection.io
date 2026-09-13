# Map LOGGER_LEVEL / -l (loguru names) onto the stdlib logging package.
# loguru and logging are independent; werkzeug's access logger only reads the latter.

import logging

# loguru SUCCESS is 25. Stdlib has no TRACE; map it to DEBUG so access lines still show.
_LOGURU_TO_STDLIB = {
    'TRACE': logging.DEBUG,
    'DEBUG': logging.DEBUG,
    'INFO': logging.INFO,
    'SUCCESS': 25,
    'WARNING': logging.WARNING,
    'WARN': logging.WARNING,
    'ERROR': logging.ERROR,
    'CRITICAL': logging.CRITICAL,
}


def stdlib_level_from_logger_level(level):
    if isinstance(level, int):
        return level
    name = str(level).upper()
    try:
        return _LOGURU_TO_STDLIB[name]
    except KeyError:
        raise ValueError(f'Unknown logger level: {level}')


def apply_stdlib_logger_level(level):
    logging.getLogger('werkzeug').setLevel(stdlib_level_from_logger_level(level))
