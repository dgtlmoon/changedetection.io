#!/bin/bash

# run some tests and look if the 'custom-browser-search-string=1' connect string appeared in the correct containers

# enable debug
set -x

# A extra browser is configured, but we never chose to use it, so it should NOT show in the logs
docker run --rm -e "PLAYWRIGHT_DRIVER_URL=ws://browserless:3000" --network changedet-network test-changedetectionio  bash -c 'cd changedetectionio;pytest tests/custom_browser_url/test_custom_browser_url.py::test_request_not_via_custom_browser_url'
docker logs browserless-custom-url &>log.txt
grep 'custom-browser-search-string=1' log.txt
if [ $? -ne 0 ]
then
  echo "saw a request in 'browserless-custom-url' container with 'custom-browser-search-string=1' when I should not"
  exit 1
fi

docker logs browserless &>log.txt
grep 'custom-browser-search-string=1' log.txt
if [ $? -ne 0 ]
then
  echo "saw a request in 'browser' container with 'custom-browser-search-string=1' when I should not"
  exit 1
fi

# Special connect string should appear in the custom-url container, but not in the 'default' one
docker run --rm -e "PLAYWRIGHT_DRIVER_URL=ws://browserless:3000" --network changedet-network test-changedetectionio  bash -c 'cd changedetectionio;pytest tests/custom_browser_url/test_custom_browser_url.py::test_request_via_custom_browser_url'
docker logs browserless-custom-url &>log.txt
grep 'custom-browser-search-string=1' log.txt
if [ $? -ne 1 ]
then
  echo "Did not see request in 'browserless-custom-url' container with 'custom-browser-search-string=1' when I should"
  exit 1
fi

docker logs browserless &>log.txt
grep 'custom-browser-search-string=1' log.txt
if [ $? -ne 0 ]
then
  echo "saw a request in 'browser' container with 'custom-browser-search-string=1' when I should not"
  exit 1
fi


