#!/bin/bash
set -eu

DATASTORE_PATH="${DATASTORE_PATH:-/datastore}"

# -----------------------------------------------------------------------
# Phase 1: Running as root — fix up PUID/PGID and datastore ownership,
#           then re-exec as the unprivileged changedetection user via gosu.
# -----------------------------------------------------------------------
if [ "$(id -u)" = '0' ]; then
    PUID=${PUID:-911}
    PGID=${PGID:-911}

    groupmod -o -g "$PGID" changedetection
    usermod -o -u "$PUID" changedetection

    # Keep /extra_packages writable by the (potentially re-mapped) user
    chown changedetection:changedetection /extra_packages

    # One-time ownership migration: only chown if the datastore isn't already
    # owned by the target UID (e.g. existing root-owned installations).
    if [ -z "${SKIP_CHOWN:-}" ]; then
        datastore_uid=$(stat -c '%u' "$DATASTORE_PATH")
        if [ "$datastore_uid" != "$PUID" ]; then
            echo "Updating $DATASTORE_PATH ownership to $PUID:$PGID (one-time migration)..."
            chown -R changedetection:changedetection "$DATASTORE_PATH"
            echo "Done."
        fi
    fi

    # Fix SSL certificate permissions so the unprivileged user can read them.
    # SSL_CERT_FILE / SSL_PRIVKEY_FILE may be relative (to /app) or absolute.
    fix_ssl_perm() {
        local file="$1" mode="$2"
        [ -z "$file" ] && return
        [ "${file:0:1}" != "/" ] && file="/app/$file"
        if [ -f "$file" ]; then
            chown changedetection:changedetection "$file"
            chmod "$mode" "$file"
        fi
    }
    fix_ssl_perm "${SSL_CERT_FILE:-}" 644
    fix_ssl_perm "${SSL_PRIVKEY_FILE:-}" 600

    # Re-exec this script as the unprivileged user
    exec gosu changedetection:changedetection "$0" "$@"
fi

# -----------------------------------------------------------------------
# Phase 2: Running as unprivileged user — install any EXTRA_PACKAGES into
#           /extra_packages (already on PYTHONPATH) then exec the app.
# -----------------------------------------------------------------------

# Install additional packages from EXTRA_PACKAGES env var.
# Uses a marker file in the datastore to avoid reinstalling on every restart.
if [ -n "${EXTRA_PACKAGES:-}" ]; then
    INSTALLED_MARKER="${DATASTORE_PATH}/.extra_packages_installed"
    if [ ! -f "$INSTALLED_MARKER" ] || [ "$(cat "$INSTALLED_MARKER" 2>/dev/null)" != "$EXTRA_PACKAGES" ]; then
        echo "Installing extra packages: $EXTRA_PACKAGES"
        pip3 install --target=/extra_packages --no-cache-dir $EXTRA_PACKAGES
        echo "$EXTRA_PACKAGES" > "$INSTALLED_MARKER"
        echo "Extra packages installed successfully"
    else
        echo "Extra packages already installed: $EXTRA_PACKAGES"
    fi
fi

exec "$@"
