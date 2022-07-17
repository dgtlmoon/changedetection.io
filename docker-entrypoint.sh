#!/bin/bash

set -eu

DATASTORE_DIR="${DATASTORE_DIR:-/datastore}"

# If the first argument looks like a flag, assume we want to run changedetection
if [ "${1:0:1}" = '-' ]; then
    set -- python ./changedetection.py -d "$DATASTORE_DIR" "$@"
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
    find "$DATASTORE_DIR" \! -user changedetection -exec chown changedetection '{}' +

    # Restart this script as an unprivileged user
    exec gosu changedetection:changedetection "$BASH_SOURCE" "$@"
fi

exec "$@"
