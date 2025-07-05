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

    # Check if the supplied uid/gid grants write permissions on the datastore
    # root directory. Only if it does not, chown it recursively.
    # In my testing, `test -w "$DATASTORE_PATH"` did not work reliably.
    tempfile="$DATASTORE_PATH/.check-writable"
    gosu changedetection:changedetection bash -c ">> '$tempfile'" &&
        rm -f "$tempfile" ||
        chown -R changedetection:changedetection "$DATASTORE_PATH" ||
        (
            echo "Failed to change permissions on $DATASTORE_PATH. Ensure it is writable by $PUID:$PGID" >&2
            exit 1
        )

    # Ensure the home directory's permissions are adjusted as well.
    chown -R changedetection:changedetection ~changedetection

    # Restart this script as an unprivileged user
    exec gosu changedetection:changedetection "$BASH_SOURCE" "$@"
fi

exec "$@"
