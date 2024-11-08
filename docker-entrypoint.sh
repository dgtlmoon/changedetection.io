#!/bin/bash

set -eu

DATASTORE_PATH="${DATASTORE_PATH:-/datastore}"

# If the first argument looks like a flag, assume we want to run changedetection
if [ "${1:0:1}" = '-' ]; then
    set -- python /app/changedetection.py "$@"
fi

# If we're running as root, by default make sure process uid/gid
# and datadir permissions are correct. This can be skipped by setting
# KEEP_PRIVILEGES to something non-empty.
if [ "$(id -u)" = '0' -a -z "${KEEP_PRIVILEGES:-}" ]; then
    PUID=${PUID:-911}
    PGID=${PGID:-911}

    groupmod -o -g "$PGID" changedetection
    usermod -o -u "$PUID" changedetection

    # Look for files in datadir not owned by the correct user and chown them
    find "$DATASTORE_PATH" \! -user changedetection -exec chown changedetection '{}' +
    chown -R changedetection:changedetection ~changedetection

    # Restart this script as an unprivileged user
    exec gosu changedetection:changedetection "$BASH_SOURCE" "$@"
fi

exec "$@"
