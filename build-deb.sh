#!/bin/bash
set -e

echo "========================================"
echo "Building changedetection.io Debian package"
echo "========================================"

# Check if running on Debian-based system
if ! command -v dpkg-buildpackage &> /dev/null; then
    echo "Error: dpkg-buildpackage not found. Install with:"
    echo "  sudo apt-get install dpkg-dev debhelper dh-python python3-all python3-setuptools"
    exit 1
fi

# Clean previous builds
echo "Cleaning previous builds..."
rm -rf debian/.debhelper debian/changedetection.io debian/files debian/*.debhelper* debian/*.substvars
rm -f ../changedetection.io_*.deb ../changedetection.io_*.buildinfo ../changedetection.io_*.changes

# Build the package
echo "Building package..."
dpkg-buildpackage -us -uc -b

echo ""
echo "========================================"
echo "Build complete!"
echo "========================================"
echo ""
echo "Package created at:"
ls -lh ../changedetection.io_*.deb
echo ""
echo "To install locally:"
echo "  sudo dpkg -i ../changedetection.io_*.deb"
echo "  sudo apt-get install -f  # If there are dependency issues"
echo ""
echo "To test in a clean environment:"
echo "  docker run --rm -it -v \$(pwd)/..:/build debian:bookworm bash"
echo "  # Inside container:"
echo "  apt-get update && apt-get install -y /build/changedetection.io_*.deb"
echo "  systemctl status changedetection.io"
