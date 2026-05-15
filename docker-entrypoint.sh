#!/bin/bash
set -e

# Install additional Python packages from the EXTRA_PACKAGES env var.
#
# Why no marker / skip-cache:
# A previous version of this script wrote a marker file to
# /datastore/.extra_packages_installed and skipped pip when it was present.
# That marker lived on the persistent /datastore volume, but the pip-installed
# packages live in the container's writable layer — so after a `docker compose
# down && up` (or any container recreation) the packages were gone while the
# marker remained, and the script wrongly believed everything was installed.
# See: https://github.com/dgtlmoon/changedetection.io/issues/4140
#
# Running pip on every start is correct by construction: when the requirements
# are already satisfied, pip is a fast no-op ("Requirement already satisfied"),
# adding ~1s per package. That's a small price for not lying about the install
# state — and pip's own resolver is the authoritative check, not a flat file.
if [ -n "$EXTRA_PACKAGES" ]; then
    echo "Ensuring extra packages installed: $EXTRA_PACKAGES"
    pip3 install --no-cache-dir $EXTRA_PACKAGES
fi

# Execute the main command
exec "$@"
