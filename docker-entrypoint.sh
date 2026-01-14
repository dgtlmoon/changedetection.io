#!/bin/bash
set -e

# Install additional packages from EXTRA_PACKAGES env var
# Uses a marker file to avoid reinstalling on every container restart
INSTALLED_MARKER="/datastore/.extra_packages_installed"
CURRENT_PACKAGES="$EXTRA_PACKAGES"

if [ -n "$EXTRA_PACKAGES" ]; then
    # Check if we need to install/update packages
    if [ ! -f "$INSTALLED_MARKER" ] || [ "$(cat $INSTALLED_MARKER 2>/dev/null)" != "$CURRENT_PACKAGES" ]; then
        echo "Installing extra packages: $EXTRA_PACKAGES"
        pip3 install --no-cache-dir $EXTRA_PACKAGES

        if [ $? -eq 0 ]; then
            echo "$CURRENT_PACKAGES" > "$INSTALLED_MARKER"
            echo "Extra packages installed successfully"
        else
            echo "ERROR: Failed to install extra packages"
            exit 1
        fi
    else
        echo "Extra packages already installed: $EXTRA_PACKAGES"
    fi
fi

# Execute the main command
exec "$@"
