#!/bin/bash

# exit when any command fails
set -e
# enable debug
set -x

docker run --rm -e "PLAYWRIGHT_DRIVER_URL=ws://browserless:3000" --network changedet-network test-changedetectionio  bash -c 'cd changedetectionio;pytest tests/custom_browser_url/test_custom_browser_url.py::test_request_via_custom_browser_url'
docker logs browserless-custom-url

